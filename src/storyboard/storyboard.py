#!/usr/bin/env python3

"""Generate video storyboards with metadata reports."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import pkg_resources
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

from storyboard import fflocate
from storyboard.frame import extract_frame as _extract_frame
from storyboard import metadata
from storyboard import util
from storyboard.version import __version__


# load default font
DEFAULT_FONT_FILE = pkg_resources.resource_filename(
    __name__,
    'SourceCodePro-Regular.otf'
)
DEFAULT_FONT_SIZE = 16


# pylint: disable=too-many-locals,invalid-name
# In this file we use a lot of short local variable names to save space.
# These short variable names are carefully documented when not obvious.


class Font(object):

    """Wrapper for a font loaded by PIL.ImageFont.

    Parameters
    ----------
    font_file : str
        Path to the font file to be loaded. If ``None``, load the
        default font defined by the module variable
        ``DEFAULT_FONT_FILE``. Default is ``None``. Note that the font
        must be supported by FreeType.
    font_size : int
        Font size to be loaded. If ``None``, use the default font size
        defined by the module variable ``DEFAULT_FONT_SIZE``. Default is
        ``None``.

    Raises
    ------
    OSError:
        If the font cannot be loaded (by ``PIL.ImageFont.truetype``).

    Attributes
    ----------
    obj
        A Pillow font object, e.g., of the type
        ``PIL.ImageFont.FreeTypeFont``.
    size : int
        The font size.

    Notes
    -----
    We are creating this wrapper because there's no guarantee that a
    font loaded by Pillow will have the ``.size`` property, and
    sometimes it certainly doesn't (try
    ``PIL.ImageFont.load_default()``, for instance). The font size,
    however, is crucial for some of other drawings, so we would like to
    keep it around all the time.

    """

    # pylint: disable=too-few-public-methods

    def __init__(self, font_file=None, font_size=None):
        """Initialize the Font class.

        See module docstring for parameters of the constructor.

        """

        if font_file is None:
            font_file = DEFAULT_FONT_FILE
        if font_size is None:
            font_size = DEFAULT_FONT_SIZE

        try:
            self.obj = ImageFont.truetype(font_file, size=font_size)
        except IOError:
            raise OSError("font file '%s' cannot be loaded" % font_file)
        self.size = font_size


def draw_text_block(canvas, xy, text, params=None):
    """Draw a block of text.

    You need to specify a canvas to draw upon. If you are not sure about
    the size of the canvas, there is a `dry_run` option (see "Other
    Parameters" that help determine the size of the text block before
    creating the canvas.

    Parameters
    ----------
    canvas : PIL.ImageDraw.Image
        The canvas to draw the text block upon. If the `dry_run` option
        is on (see "Other Parameters"), `canvas` can be ``None``.
    xy : tuple
        Tuple ``(x, y)`` consisting of x and y coordinates of the
        topleft corner of the text block.
    text : str
        Text to be drawn, can be multiline.
    params : dict, optional
        Optional parameters enclosed in a dict. Default is ``None``.
        See the "Other Parameters" section for understood key/value
        pairs.

    Returns
    -------
    (width, height)
        Size of text block.

    Other Parameters
    ----------------
    font : Font, optional
        Default is the font constructed by ``Font()`` without arguments.
    color : color, optional
        Color of text; can be in any color format accepted by Pillow
        (used for the ``fill`` argument of
        ``PIL.ImageDraw.Draw.text``). Default is ``'black'``.
    spacing : float, optional
        Line spacing as a float. Default is 1.2.
    dry_run : bool, optional
        If ``True``, do not draw anything, only return the size of the
        text block. Default is ``False``.

    """

    if params is None:
        params = {}
    x, y = xy
    font = params['font'] if 'font' in params else Font()
    color = params['color'] if 'color' in params else 'black'
    spacing = params['spacing'] if 'spacing' in params else 1.2
    dry_run = params['dry_run'] if 'dry_run' in params else False

    if not dry_run:
        draw = ImageDraw.Draw(canvas)

    line_height = int(round(font.size * spacing))
    width = 0
    height = 0
    for line in text.splitlines():
        w, _ = draw.textsize(line, font=font.obj)
        if not dry_run:
            draw.text((x, y), line, fill=color, font=font.obj)
        if w > width:
            width = w  # update width to that of the current widest line
        height += line_height
        y += line_height
    return (width, height)


def create_thumbnail(frame, width, params=None):
    """Create thumbnail of a video frame.

    The timestamp of the frame can be overlayed to the thumbnail. See
    "Other Parameters" to how to enable this feature and relevant
    options.

    Parameters
    ----------
    frame : storyboard.frame.Frame
        The video frame to be thumbnailed.
    width : int
        Width of the thumbnail.
    params : dict, optional
        Optional parameters enclosed in a dict. Default is ``None``.
        See the "Other Parameters" section for understood key/value
        pairs.

    Returns
    -------
    thumbnail : PIL.Image.Image

    Other Parameters
    ----------------
    aspect_ratio : float, optional
        Aspect ratio of the thumbnail. If ``None``, use the aspect ratio
        (only considering the pixel dimensions) of the frame. Default is
        ``None``.
    draw_timestamp : bool, optional
        Whether to draw frame timestamp over the timestamp. Default is
        ``False``.
    timestamp_font : Font, optional
        Font for the timestamp, if `draw_timestamp` is ``True``.
        Default is the font constructed by ``Font()`` without arguments.
    timestamp_align : {'right', 'center', 'left'}, optional
        Horizontal alignment of the timestamp over the thumbnail, if
        `draw_timestamp` is ``True``. Default is ``'right'``. Note that
        the timestamp is always vertically aligned towards the bottom of
        the thumbnail.

    """

    if params is None:
        params = {}
    if 'aspect_ratio' in params:
        aspect_ratio = params['aspect_ratio']
    else:
        image_width, image_height = frame.image.size
        aspect_ratio = image_width / image_height
    height = int(round(width / aspect_ratio))
    size = (width, height)
    draw_timestamp = (params['draw_timestamp'] if 'draw_timestamp' in params
                      else False)
    if draw_timestamp:
        timestamp_font = (params['timestamp_font']
                          if 'timestamp_font' in params else Font())
        timestamp_align = (params['timestamp_align']
                           if 'timestamp_align' in params else 'right')

    thumbnail = frame.image.resize(size, Image.LANCZOS)

    if draw_timestamp:
        draw = ImageDraw.Draw(thumbnail)

        timestamp_text = util.humantime(frame.timestamp, ndigits=0)
        timestamp_width, timestamp_height = \
            draw.textsize(timestamp_text, timestamp_font.obj)

        # calculate upperleft corner of the timestamp overlay
        # we hard code a margin of 5 pixels
        timestamp_y = height - 5 - timestamp_height
        if timestamp_align == 'right':
            timestamp_x = width - 5 - timestamp_width
        elif timestamp_align == 'left':
            timestamp_x = 5
        elif timestamp_align == 'center':
            timestamp_x = int((width - timestamp_width) / 2)
        else:
            raise ValueError("timestamp alignment option '%s' not recognized"
                             % timestamp_align)

        # draw white timestamp with 1px thick black border
        for x_offset in range(-1, 2):
            for y_offset in range(-1, 2):
                draw.text((timestamp_x + x_offset, timestamp_y + y_offset),
                          timestamp_text,
                          fill='black', font=timestamp_font.obj)
        draw.text((timestamp_x, timestamp_y),
                  timestamp_text,
                  fill='white', font=timestamp_font.obj)

    return thumbnail


def tile_images(images, tile, params=None):
    """
    Combine images into a composite image through 2D tiling.

    For example, 16 thumbnails can be combined into an 4x4 array. As
    another example, three images of the same width (think of the
    metadata sheet, the bare storyboard, and the promotional banner) can
    be combined into a 1x3 array, i.e., assembled vertically.

    The image list is processed column-first.

    Note that except if you use the `tile_size` option (see "Other
    Parameters"), you should make sure that images passed into this
    function satisfy the condition that the widths of all images in each
    column and the heights of all images in each row match perfectly;
    otherwise, this function will give up and raise a ValueError.

    Parameters
    ----------
    images : list
        A list of PIL.Image.Image objects, satisfying the necessary
        height and width conditions (see explanation above).
    tile : tuple
        A tuple ``(m, n)`` indicating `m` columns and `n` rows. The
        product of `m` and `n` should be the length of `images`, or a
        `ValueError` will arise.
    params : dict, optional
        Optional parameters enclosed in a dict. Default is ``None``.
        See the "Other Parameters" section for understood key/value
        pairs.

    Returns
    -------
    PIL.Image.Image
        The composite image.

    Raises
    ------
    ValueError
        If the length of `images` does not match the product of columns
        and rows (as defined in `tile`), or the widths and heights of
        the images do not satisfy the necessary consistency conditions.

    Other Parameters
    ----------------
    tile_size : tuple, optional
        A tuple ``(width, height)``. If this parameter is specified,
        width and height consistency conditions won't be checked, and
        every image will be resized to (width, height) when
        combined. Default is ``None``.
    tile_spacing : tuple, optional
        A tuple ``(hor, ver)`` specifying the horizontal and vertical
        spacing between adjacent tiles. Default is ``(0, 0)``.
    margins : tuple, optional
        A tuple ``(hor, ver)`` specifying the horizontal and vertical
        margins ``(padding)`` around the combined image. Default is
        ``(0, 0)``.
    canvas_color : color, optional
        A color in any format recognized by Pillow. This is only
        relevant if you have nonzero tile spacing or margins, when the
        background shines through the spacing or margins. Default is
        ``'white'``.
    close_separate_images : bool
        Whether to close the separate after combining. Closing the
        images will release the corresponding resources. Default is
        ``False``.

    """

    # pylint: disable=too-many-branches

    if params is None:
        params = {}
    cols, rows = tile
    if len(images) != cols * rows:
        msg = "{} images cannot fit into a {}x{}={} array".format(
            len(images), cols, rows, cols * rows)
        raise ValueError(msg)
    hor_spacing, ver_spacing = (params['tile_spacing']
                                if 'tile_spacing' in params
                                else (0, 0))
    hor_margin, ver_margin = (params['margins'] if 'margins' in params
                              else (0, 0))
    canvas_color = (params['canvas_color'] if 'canvas_color' in params
                    else 'white')
    close_separate_images = (params['close_separate_images']
                             if 'close_separate_images' in params
                             else False)
    if 'tile_size' in params and params['tile_size'] is not None:
        tile_size = params['tile_size']
        tile_width, tile_height = tile_size
        canvas_width = (tile_width * cols + hor_spacing * (cols - 1) +
                        hor_margin * 2)
        canvas_height = (tile_height * rows + ver_spacing * (rows - 1) +
                         ver_margin * 2)
        resize = True
    else:
        # check column width consistency, bark if not
        # calculate total width along the way
        canvas_width = hor_spacing * (cols - 1) + hor_margin * 2
        for col in range(0, cols):
            # reference width set by the first image in the column
            ref_index = 0 * cols + col
            ref_width, ref_height = images[ref_index].size
            canvas_width += ref_width
            for row in range(1, rows):
                index = row * cols + col
                width, height = images[index].size
                if width != ref_width:
                    msg = ("the width of image #{} "
                           "(row #{}, col #{}, {}x{}) "
                           "does not agree with that of image #{} "
                           "(row #{}, col #{}, {}x{})".format(
                               index, row, col, width, height,
                               ref_index, 0, col, ref_width, ref_height,
                           ))
                    raise ValueError(msg)
        # check row height consistency, bark if not
        # calculate total height along the way
        canvas_height = ver_spacing * (rows - 1) + ver_margin * 2
        for row in range(0, rows):
            # reference width set by the first image in the column
            ref_index = row * cols + 0
            ref_width, ref_height = images[ref_index].size
            canvas_height += ref_height
            for col in range(1, cols):
                index = row * cols + col
                width, height = images[index].size
                if height != ref_height:
                    msg = ("the height of image #{} "
                           "(row #{}, col #{}, {}x{}) "
                           "does not agree with that of image #{} "
                           "(row #{}, col #{}, {}x{})".format(
                               index, row, col, width, height,
                               ref_index, 0, col, ref_width, ref_height,
                           ))
                    raise ValueError(msg)
        # passed tests, will assemble as is
        resize = False

    # start assembling images
    canvas = Image.new('RGBA', (canvas_width, canvas_height), canvas_color)
    y = ver_margin
    for row in range(0, rows):
        x = hor_margin
        for col in range(0, cols):
            image = images[row * cols + col]

            if resize:
                canvas.paste(image.resize(tile_size, Image.LANCZOS), (x, y))
            else:
                canvas.paste(image, (x, y))

            # accumulate width of this column, as well as horizontal spacing
            x += image.size[0] + hor_spacing
        # accumulate height of this row, as well as vertical spacing
        y += images[row * cols + 0].size[1] + ver_spacing

    if close_separate_images:
        for image in images:
            image.close()

    return canvas


class StoryBoard(object):
    """Class for storing video thumbnails and metadata, and creating storyboard
    on request.
    """
    # pylint: too-few-public-methods

    def __init__(self, video, num_thumbnails=16,
                 ffmpeg_bin='ffmpeg', ffprobe_bin='ffprobe', codec='png',
                 print_progress=False):
        self.video = metadata.Video(video, params={
            'ffprobe_bin': ffprobe_bin,
            'print_progress': print_progress,
        })
        self.frames = []

    def storyboard(self,
                   padding=(10, 10), include_banner=True, print_progress=False,
                   font=None, font_size=16, text_spacing=1.2,
                   text_color='black',
                   include_sha1sum=True,
                   tiling=(4, 4), tile_width=480, tile_aspect_ratio=None,
                   tile_spacing=(4, 3),
                   draw_timestamp=True):
        """Create storyboard.

        Keyword arguments:

        General options:
        padding        -- (horizontal, vertical) padding to the entire
                          storyboard; default is (10, 10)
        include_banner -- boolean, whether or not to include a promotional
                          banner for this tool at the bottom; default is True
        print_progress -- boolean, whether or not to print progress
                          information; default is False

        Text options:
        font         -- a font object loaded from PIL.ImageFont; default is
                        SourceCodePro-Regular (included) at 16px
        font_size    -- font size in pixels, default is 16 (should match font)
        text_spacing -- line spacing as a float (text line height will be
                        calculated from round(font_size * text_spacing));
                        default is 1.2
        text_color   -- text color, either as RGBA 4-tuple or color name
                        string recognized by ImageColor; default is 'black'

        Metadata options:
        include_sha1sum -- boolean, whether or not to include SHA-1 checksum as
                           a printed metadata field; keep in mind that SHA-1
                           calculation is slow for large videos

        Tile options:
        tiling            -- (m, n) means m tiles horizontally and n tiles
                             vertically; m and n must satisfy m * n =
                             num_thumbnails (specified in __init__); default is
                             (4, 4)
        tile_width        -- width of each tile (int), default is 480
        tile_aspect_ratio -- aspect ratio of each tile; by default it is
                             determined first from the display aspect ratio
                             (DAR) of the video and then from the pixel
                             dimensions, but in case the result is wrong, you
                             can still specify the aspect ratio this way
        tile_spacing      -- (horizontal_spaing, vertical_spacing), default is
                             (4, 3), which means (before applying the global
                             padding), the tiles will be spaced from the left
                             and right edges by 4 pixels, and will have a
                             4 * 2 = 8 pixel horizontal spacing between two
                             adjacent tiles; same goes for vertical spacing;

        Timestamp options:
        draw_timestamp  -- boolean, whether or not to draw timestamps on the
                           thumbnails (lower-right corner); default is True

        Return value:
        Storyboard as a PIL.Image.Image image.
        """
        # !TO DO: check argument types and n * m = num_thumbnails
        if font is None:
            font_file = pkg_resources.resource_filename(
                __name__,
                'SourceCodePro-Regular.otf'
            )
            font = ImageFont.truetype(font_file, size=16)
        if tile_aspect_ratio is None:
            tile_aspect_ratio = self.video.dar

        # draw storyboard, meta sheet, and banner
        if print_progress:
            sys.stderr.write("Drawing main storyboard...\n")
        storyboard = self._draw_storyboard(tiling, tile_width,
                                           tile_aspect_ratio, tile_spacing,
                                           draw_timestamp,
                                           font)
        total_width = storyboard.size[0]
        if print_progress:
            sys.stderr.write("Generating metadata sheet...\n")
        meta_sheet = self._draw_meta_sheet(total_width, tile_spacing, font,
                                           font_size, text_spacing, text_color,
                                           include_sha1sum, print_progress)

        # assemble the parts
        if include_banner:
            if print_progress:
                sys.stderr.write("Drawing the bottom banner...\n")
            banner = self._draw_banner(total_width,
                                       font, font_size, text_color)
            total_height = (storyboard.size[1] + meta_sheet.size[1] +
                            banner.size[1])
            # add padding
            hp = padding[0]  # horizontal padding
            vp = padding[1]  # vertical padding
            total_width += 2 * hp
            total_height += 2 * vp
            assembled = Image.new('RGBA', (total_width, total_height), 'white')
            if print_progress:
                sys.stderr.write("Assembling parts...\n")
            assembled.paste(meta_sheet, (hp, vp))
            assembled.paste(storyboard, (hp, vp + meta_sheet.size[1]))
            assembled.paste(banner,
                            (hp, vp + meta_sheet.size[1] + storyboard.size[1]))
        else:
            total_height = storyboard.size[1] + meta_sheet.size[1]
            # add padding
            hp = padding[0]  # horizontal padding
            vp = padding[1]  # vertical padding
            total_width += 2 * hp
            total_height += 2 * vp
            assembled = Image.new('RGBA', (total_width, total_height), 'white')
            assembled.paste(meta_sheet, (hp, vp))
            assembled.paste(storyboard, (hp, vp + meta_sheet.size[1]))

        return assembled

    def gen_frames(self, count, params=None):
        """Extract equally spaced frames from the video.

        When tasked with extracting N frames, this method extracts them
        at positions 1/2N, 3/2N, 5/2N, ... , (2N-1)/2N of the video. The
        extracted frames are stored in the `frames` attribute.

        Note that new frames are extracted only if the number of
        existing frames in the `frames` attribute doesn't match the
        specified `count` (0 at instantiation), in which case new frames
        are extracted to match the specification, and the `frames`
        attribute is overwritten.

        Paramters
        ----------
        count : int
            Number of (equally-spaced) frames to generate.
        params : dict, optional
            Optional parameters enclosed in a dict. Default is
            ``None``. See the "Other Parameters" section for understood
            key/value pairs.

        Returns
        -------
        None
            Access the generated frames through the `frames` attribute.

        RAISES
        ------
        OSError
            If frame extraction with FFmpeg fails.

        Other Parameters
        ----------------
        print_progress : bool, optional
            Whether to print progress information (to stderr). Default
            is False.

        """

        if params is None:
            params = {}
        print_progress = (params['print_progress']
                          if 'print_progress' in params else False)

        if len(self.frames) == count:
            return

        duration = self.video.duration
        interval = duration / count
        timestamps = [interval * (i + 1/2) for i in range(0, count)]
        counter = 0
        for timestamp in timestamps:
            counter += 1
            if print_progress:
                sys.stderr.write("\rExtracting frame %d/%d..." %
                                 (counter, count))
            try:
                frame = _extract_frame(self.video, timestamp, params={
                    'ffmpeg_bin': self._bins[0],
                    'codec' : self._frame_codec,
                })
                self.frames.append(frame)
            except:
                # \rExtracting frame %d/%d... isn't terminated by
                # newline yet
                if print_progress:
                    sys.stderr.write("\n")
                raise
        if print_progress:
            sys.stderr.write("\n")

    def _gen_bare_storyboard(self, tile, thumbnail_width, params=None):
        """Generate bare storyboard (thumbnails only).

        Paramters
        ----------
        tile : tuple
            A tuple ``(cols, rows)`` specifying the number of columns
            and rows for the array of thumbnails.
        thumbnail_width : int
            Width of each thumbnail.
        params : dict, optional
            Optional parameters enclosed in a dict. Default is
            ``None``. See the "Other Parameters" section for understood
            key/value pairs.

        Returns
        -------
        base_storyboard : PIL.Image.Image

        Other Parameters
        ----------------
        tile_spacing : tuple, optional
            See the `tile_spacing` parameter of the `tile_images`
            function. Default is ``(0, 0)``.

        background_color : color, optional
            See the `canvas_color` paramter of the `tile_images`
            function. Default is ``'white'``.

        thumbnail_aspect_ratio : float, optional
            Aspect ratio of generated thumbnails. If ``None``, first try
            to use ``self.dar``, then the aspect ratio of the frames if
            ``self.dar`` is not available. Default is ``None``.

        draw_timestamp : bool, optional
            See the `draw_timestamp` parameter of the `create_thumbnail`
            function. Default is ``False``.
        timestamp_font : Font, optional
            See the `timestamp_font` parameter of the `create_thumbnail`
            function. Default is the font constructed by ``Font()`` with
            no arguments.
        timestamp_align : {'right', 'center', 'left'}, optional
            See the `timestamp_align` parameter of the
            `create_thumbnail` function. Default is ``'right'``.

        print_progress : bool, optional
            Whether to print progress information (to stderr). Default
            is False.

        """

        if params is None:
            params = {}
        tile_spacing = (params['tile_spacing'] if 'tile_spacing' in params
                        else (0, 0))
        background_color = (params['background_color']
                            if 'background_color' in params else 'white')
        if 'thumbnail_aspect_ratio' in params:
            thumbnail_aspect_ratio = params['thumbnail_aspect_ratio']
        elif self.video.dar is not None:
            thumbnail_aspect_ratio = self.video.dar
        else:
            # defer calculation to after generating frames
            thumbnail_aspect_ratio = None
        draw_timestamp = (params['draw_timestamp']
                          if 'draw_timestamp' in params else False)
        if draw_timestamp:
            timestamp_font = (params['timestamp_font']
                              if 'timestamp_font' in params else Font())
            timestamp_align = (params['timestamp_align']
                               if 'timestamp_align' in params else 'right')
        print_progress = (params['print_progress']
                          if 'print_progress' in params else False)

        cols, rows = tile
        if (not(isinstance(cols, int) and isinstance(rows, int) and
                cols > 0 and rows > 0)):
            raise ValueError('tile is not a tuple of positive integers')
        thumbnail_count = cols * rows
        self.gen_frames(cols * rows, params={
            'print_progress': print_progress,
        })
        if thumbnail_aspect_ratio is None:
            frame_size = self.frames[0].image.size
            thumbnail_aspect_ratio = frame_size[0] / frame_size[1]

        thumbnails = []
        counter = 0
        for frame in self.frames:
            counter += 1
            if print_progress:
                sys.stderr.write("\rGenerating thumbnail %d/%d..." %
                                 (counter, thumbnail_count))
            thumbnails.append(create_thumbnail(frame, thumbnail_width, params={
                'aspect_ratio': thumbnail_aspect_ratio,
                'draw_timestamp': draw_timestamp,
                'timestamp_font': timestamp_font,
                'timestamp_align': timestamp_align,
            }))
        if print_progress:
            sys.stderr.write("\n")

        if print_progress:
            sys.stderr.write("Tiling thumbnails...\n")
        return tile_images(thumbnails, tile, params={
            'tile_spacing': tile_spacing,
            'canvas_color': background_color,
            'close_separate_images': True,
        })

    def _gen_metadata_sheet(self, total_width, params=None):
        """Generate metadata sheet.

        Parameters
        ----------
        total_width : int
            Total width of the metadata sheet. Usually determined by the
            width of the bare storyboard.
        params : dict, optional
            Optional parameters enclosed in a dict. Default is
            ``None``. See the "Other Parameters" section for understood
            key/value pairs.

        Returns
        -------
        metadata_sheet : PIL.Image.Image

        Other Parameters
        ----------------
        text_font : Font, optional
            Default is the font constructed by ``Font()`` without
            arguments.
        text_color: color, optional
            Default is 'black'.
        text_spacing : float, optional
            Line spacing as a float. Default is 1.2.
        background_color: color, optional
            Default is 'white'.
        include_sha1sum: bool, optional
            See the `include_sha1sum` option of
            `storyboard.metadata.Video.format_metadata`. Beware that
            computing SHA-1 digest is an expensive operation.
        print_progress : bool, optional
            Whether to print progress information (to stderr). Default
            is False.

        """

        if params is None:
            params = {}
        text_font = params['text_font'] if 'text_font' in params else Font()
        text_color = (params['text_color'] if 'text_color' in params
                      else 'black')
        text_spacing = (params['text_spacing'] if 'text_spacing' in params
                        else 1.2)
        background_color = (params['background_color']
                            if 'background_color' in params else 'white')
        include_sha1sum = (params['include_sha1sum']
                           if 'include_sha1sum' in params else False)
        print_progress = (params['print_progress']
                          if 'print_progress' in params else False)

        text = self.video.format_metadata(params={
            'include_sha1sum': include_sha1sum,
            'print_progress': print_progress,
        })

        _, total_height = draw_text_block(None, (0, 0), text, params={
            'font': text_font,
            'spacing': text_spacing,
            'dry_run': True,
        })

        metadata_sheet = Image.new('RGBA', (total_width, total_height),
                                   background_color)
        draw_text_block(metadata_sheet, (0, 0), text, params={
            'font': text_font,
            'color': text_color,
            'spacing': text_spacing,
        })

        return metadata_sheet

    @staticmethod
    def _gen_promotional_banner(total_width, params=None):
        """Generate promotion banner.

        This is the promotional banner for the storyboard package.

        Parameters
        ----------
        total_width : int
            Total width of the metadata sheet. Usually determined by the
            width of the bare storyboard.
        params : dict, optional
            Optional parameters enclosed in a dict. Default is
            ``None``. See the "Other Parameters" section for understood
            key/value pairs.

        Returns
        -------
        banner : PIL.Image.Image

        Other Parameters
        ----------------
        text_font : Font, optional
            Default is the font constructed by ``Font()`` without
            arguments.
        text_color: color, optional
            Default is 'black'.
        background_color: color, optional
            Default is 'white'.

        """

        if params is None:
            params = {}
        text_font = params['text_font'] if 'text_font' in params else Font()
        text_color = (params['text_color'] if 'text_color' in params
                      else 'black')
        background_color = (params['background_color']
                            if 'background_color' in params else 'white')

        text = ("Generated by storyboard version %s. "
                "Fork me on GitHub: github.com/zmwangx/storyboard"
                % __version__)
        text_width, total_height = draw_text_block(None, (0, 0), text, params={
            'font': text_font,
            'dry_run': True,
        })

        banner = Image.new('RGBA', (total_width, total_height),
                           background_color)
        # center the text -- calculate the x coordinate of its topleft
        # corner
        text_x = int((total_width - text_width) / 2)
        draw_text_block(banner, (text_x, 0), text, params={
            'font': text_font,
            'color': text_color,
        })

        return banner


def main():
    """CLI interface."""
    description = "Generate video storyboards with metadata reports."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('videos', metavar='VIDEO', nargs='+',
                        help="path(s) to the video file(s)")
    args = parser.parse_args()

    # process arguments
    include_sha1sum = True  # ! for the moment
    print_progress = True  # ! for the moment
    # detect ffmpeg and ffprobe binaries
    # ! guessing for the moment
    # ! will consider command line options and config file
    ffmpeg_bin, ffprobe_bin = fflocate.guess_bins()
    try:
        fflocate.check_bins((ffmpeg_bin, ffprobe_bin))
    except OSError as err:
        sys.stderr.write("fatal error: %s\n" % str(err))
        return 1

    returncode = 0
    for video in args.videos:
        try:
            sb = StoryBoard(
                video,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
                print_progress=print_progress,
            )
        except OSError as err:
            sys.stderr.write("error: %s\n\n" % str(err))
            returncode = 1
            continue

        storyboard = sb.storyboard(
            include_sha1sum=include_sha1sum,
            print_progress=print_progress,
        )

        _, path = tempfile.mkstemp(suffix='.jpg', prefix='storyboard-')
        # ! will have output format and quality options
        storyboard.save(path, quality=90)
        if print_progress:
            sys.stderr.write("Done. Generated storyboard saved to:\n")
        print(path)
        if print_progress:
            sys.stderr.write("\n")
    return returncode


if __name__ == "__main__":
    exit(main())
