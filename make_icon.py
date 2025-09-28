from PIL import Image, ImageDraw

def main():
    img = Image.new('RGBA', (256, 256), (32, 96, 224, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([48, 112, 96, 152], fill=(255, 255, 255, 255))
    d.rectangle([108, 112, 124, 152], fill=(255, 255, 255, 255))
    d.rectangle([124, 112, 172, 128], fill=(255, 255, 255, 255))
    d.rectangle([124, 136, 172, 152], fill=(255, 255, 255, 255))
    d.rectangle([184, 112, 216, 152], fill=(255, 255, 255, 255))
    img.save('icon.ico', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])

if __name__ == '__main__':
    main()
