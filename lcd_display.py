import lgpio
import spidev
import time
from PIL import Image, ImageDraw, ImageFont

# Pin configuration (adjusted for swap: DC/A0 to GPIO24, RST to GPIO25)
RST_PIN = 25
DC_PIN = 24
CS_PIN = 8  # CE0

# Offsets for common ST7735 variants (adjust if image is shifted/off-screen)
X_OFFSET = 0
Y_OFFSET = 0  # Adjusted for red tab or full alignment

# Display dimensions (rotation 0: portrait 128x160)
#WIDTH = 128
#HEIGHT = 160
#Display dimensions (for landscape 90 deg: 160*128
WIDTH = 160
HEIGHT = 128

# Open GPIO and SPI
h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, RST_PIN, level=1)
lgpio.gpio_claim_output(h, DC_PIN, level=1)
lgpio.gpio_claim_output(h, CS_PIN, level=1)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.mode = 0
spi.max_speed_hz = 8000000  # Start low, increase if stable (up to 24000000)

def write_command(cmd):
    lgpio.gpio_write(h, DC_PIN, 0)
    lgpio.gpio_write(h, CS_PIN, 0)
    spi.writebytes([cmd])
    lgpio.gpio_write(h, CS_PIN, 1)

def write_data(data):
    lgpio.gpio_write(h, DC_PIN, 1)
    lgpio.gpio_write(h, CS_PIN, 0)
    chunk_size = 4096
    for i in range (0, len(data), chunk_size):
        spi.writebytes(data[i:i+chunk_size])
    lgpio.gpio_write(h, CS_PIN, 1)

def reset():
    lgpio.gpio_write(h, RST_PIN, 1)
    time.sleep(0.01)
    lgpio.gpio_write(h, RST_PIN, 0)
    time.sleep(0.01)
    lgpio.gpio_write(h, RST_PIN, 1)
    time.sleep(0.15)

def init_display():
    reset()
    write_command(0x01)  # Software reset
    time.sleep(0.15)
    write_command(0x11)  # Sleep out
    time.sleep(0.12)
#    write_command(0x21)  # Display inversion on (adjust if colors inverted)
#    time.sleep(0.005)
    write_command(0xB1)
    write_data([0x05, 0x3A, 0x3A])
    write_command(0xB2)
    write_data([0x05, 0x3A, 0x3A])
    write_command(0xB3)
    write_data([0x05, 0x3A, 0x3A, 0x05, 0x3A, 0x3A])
    write_command(0xB4)
    write_data([0x03])
    write_command(0xC0)
    write_data([0x62, 0x02, 0x04])
    write_command(0xC1)
    write_data([0xC0])
    write_command(0xC2)
    write_data([0x0D, 0x00])
    write_command(0xC3)
    write_data([0x8D, 0x6A])
    write_command(0xC4)
    write_data([0x8D, 0xEE])
    write_command(0xC5)
    write_data([0x0E])
    write_command(0x36)  # Memory access control (rotation 0, adjust byte for other rotations: e.g., 0xC8 for 180, 0xA0 for 90)
#    write_data([0xC8]) # 180 degree for upright
#    write_data([0x60]) # 90 deg for landscape, no flips
    write_data([0xA0]) # 90 deg for landscape, no flips
    write_command(0x3A)  # Pixel format 16-bit
    write_data([0x05])
    write_command(0xE0)
    write_data([0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1, 0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00, 0x00])
    write_command(0xE1)
    write_data([0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1, 0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F])
    write_command(0x29)  # Display on
    time.sleep(0.12)

def set_window(x0, y0, x1, y1):
    write_command(0x2A)  # Column addr set
    write_data([0x00, x0 + X_OFFSET, 0x00, x1 + X_OFFSET])
    write_command(0x2B)  # Row addr set
    write_data([0x00, y0 + Y_OFFSET, 0x00, y1 + Y_OFFSET])
    write_command(0x2C)  # Write RAM

def display_image(img):
    # Convert PIL image to RGB565 bytearray
    buffer = bytearray(WIDTH * HEIGHT * 2)
    pixels = img.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            color = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            idx = (y * WIDTH + x) * 2
            buffer[idx] = (color >> 8) & 0xFF
            buffer[idx + 1] = color & 0xFF
    set_window(0, 0, WIDTH - 1, HEIGHT - 1)
    write_data(buffer)

# Initialize display
init_display()

# Create image with text
# image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))  # Black background
# draw = ImageDraw.Draw(image)
#font = ImageFont.load_default()  # Small default font for test
font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 32) #larger font
# draw.text((30, 30), "Aumovio \nEng. Solutions!", font=font, fill=(0, 255, 0))  

#Display it
# display_image(image)

def display_text (text, color = (255, 255, 255)):
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))  # Black background
    draw = ImageDraw.Draw(image)
    lines = text.split('\n')
    y_pos = 20
    for line in lines:
        draw.text((10,y_pos), line, font=font, fill=color)
        y_pos += 30
    display_image(image)
    # bbox = font.getbbox(text) # Get text size
    # font_width = bbox[2] - bbox[0]
    # font_height = bbox[3] - bbox[1]
    # draw.text(
        # ((WIDTH - font_width)//2, (HEIGHT - font_height) // 2),
        # text,
        # font=font,
        # fill=color
    # )
    # draw.text((30,30), text, font=font, fill=color)
    # display_image(image)

# Comment out or remove these lines to prevent closing on import
# display_text ("AUMOVIO\n Eng. Sol.", (0,255,0))

# Cleanup (optional, for repeated runs)
#time.sleep(5)  # Keep displayed for 5 seconds
# lgpio.gpiochip_close(h)
# spi.close()

# Optional: Add this function if you want to close resources explicitly later
def cleanup():
    lgpio.gpiochip_close(h)
    spi.close()