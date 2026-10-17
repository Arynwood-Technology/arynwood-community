"""Photos as they are shared in Messages: PNG, JPEG or WebP, with everything but the picture taken
out. Phones write where a photo was taken, and on what, into the file; none of that should travel.
Members' pages shrink and re-encode photos before sending them, which already drops it: this is
the server's own check, for a page that doesn't."""
import struct

class NotAPhoto(ValueError):
    pass

def kind_of(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    return None

def plain(data):
    """(the photo without metadata, its media type, width, height), or NotAPhoto."""
    kind = kind_of(data)
    try:
        if kind == 'image/jpeg': return jpeg(data)
        if kind == 'image/png': return png(data)
        if kind == 'image/webp': return webp(data)
    except (struct.error, IndexError) as error:
        raise NotAPhoto('That photo is damaged.') from error
    raise NotAPhoto('Share photos as JPEG, PNG or WebP.')

# JPEG: keep the picture's own segments; drop APP1 to APP15 (Exif, XMP, IPTC, maker notes) and comments.
KEEP_APP = {0xE0, 0xEE}  # JFIF, and Adobe's colour transform
def jpeg(data):
    out, i, size = bytearray(data[:2]), 2, None
    while i < len(data):
        if data[i] != 0xFF: raise NotAPhoto('That photo is damaged.')
        marker = data[i + 1]
        if marker == 0xFF: i += 1; continue
        if marker == 0xDA:  # start of scan: the rest is the picture itself
            out += data[i:]; break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01: out += data[i:i + 2]; i += 2; continue
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        segment = data[i:i + 2 + length]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack('>HH', data[i + 5:i + 9]); size = (width, height)
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE) or marker in KEEP_APP: out += segment
        i += 2 + length
    if not size: raise NotAPhoto('That photo is damaged.')
    return bytes(out), 'image/jpeg', *size

# PNG: drop text, Exif and time chunks.
DROP_PNG = {b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'tIME'}
def png(data):
    out, i = bytearray(data[:8]), 8
    width, height = struct.unpack('>II', data[16:24])
    while i < len(data):
        length = struct.unpack('>I', data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        if kind not in DROP_PNG: out += data[i:i + 12 + length]
        i += 12 + length
        if kind == b'IEND': break
    return bytes(out), 'image/png', width, height

# WebP: drop the EXIF and XMP chunks, and say so in the header.
def webp(data):
    out, i, size = bytearray(), 12, None
    while i + 8 <= len(data):
        kind, length = data[i:i + 4], struct.unpack('<I', data[i + 4:i + 8])[0]
        chunk = bytearray(data[i:i + 8 + length + (length & 1)])
        if kind == b'VP8X':
            chunk[8] &= ~0x0C & 0xFF
            size = (1 + int.from_bytes(chunk[12:15], 'little'), 1 + int.from_bytes(chunk[15:18], 'little'))
        elif kind == b'VP8 ' and not size:
            size = (struct.unpack('<H', chunk[14:16])[0] & 0x3FFF, struct.unpack('<H', chunk[16:18])[0] & 0x3FFF)
        elif kind == b'VP8L' and not size:
            bits = int.from_bytes(chunk[9:13], 'little')
            size = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if kind not in (b'EXIF', b'XMP '): out += chunk
        i += 8 + length + (length & 1)
    if not size: raise NotAPhoto('That photo is damaged.')
    return b'RIFF' + struct.pack('<I', len(out) + 4) + b'WEBP' + bytes(out), 'image/webp', *size
