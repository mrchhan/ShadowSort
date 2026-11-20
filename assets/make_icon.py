from PIL import Image, ImageDraw, ImageFilter, ImageChops
S=2048; K=2  # supersample
BLUE=(43,155,255); ORANGE=(242,138,46); NAVY1=(26,38,78); NAVY2=(10,14,32)
logo=Image.open(__import__('os').path.join(__import__('os').path.dirname(__file__),'shadow-logo.png')).convert('RGB')

def rr_mask(size, r):
    m=Image.new('L',size,0); ImageDraw.Draw(m).rounded_rectangle((0,0,size[0]-1,size[1]-1),radius=r,fill=255); return m
def grad(size, c1, c2, horiz=False):
    g=Image.new('RGB',size); d=ImageDraw.Draw(g); n=size[0] if horiz else size[1]
    for i in range(n):
        t=i/max(1,n-1); c=tuple(int(c1[k]+(c2[k]-c1[k])*t) for k in range(3))
        d.line([(i,0),(i,size[1])] if horiz else [(0,i),(size[0],i)],fill=c)
    return g

canvas=Image.new('RGBA',(S,S),(0,0,0,0))
# ---- tile with drop shadow
x0,y0,x1,y1=230,230,1818,1818; R=380
sh=Image.new('L',(S,S),0); ImageDraw.Draw(sh).rounded_rectangle((x0,y0+40,x1,y1+40),radius=R,fill=150)
sh=sh.filter(ImageFilter.GaussianBlur(40)); canvas.paste((0,0,0,255),(0,0),sh)
# split border blue | orange
border=Image.new('RGB',(S,S),BLUE); ImageDraw.Draw(border).rectangle((S//2,0,S,S),fill=ORANGE)
bm=Image.new('L',(S,S),0); ImageDraw.Draw(bm).rounded_rectangle((x0,y0,x1,y1),radius=R,fill=255)
canvas.paste(border,(0,0),bm)
bw=44
inner=(x0+bw,y0+bw,x1-bw,y1-bw)
im=Image.new('L',(S,S),0); ImageDraw.Draw(im).rounded_rectangle(inner,radius=R-bw,fill=255)
bg=grad((S,S),NAVY1,NAVY2); canvas.paste(bg,(0,0),im)
# soft glow behind the photos
glow=Image.new('RGBA',(S,S),(0,0,0,0)); gd=ImageDraw.Draw(glow)
gd.ellipse((520,420,1150,1050),fill=BLUE+(110,)); gd.ellipse((900,420,1530,1050),fill=ORANGE+(90,))
glow=glow.filter(ImageFilter.GaussianBlur(120)); canvas=Image.alpha_composite(canvas, Image.composite(glow, Image.new('RGBA',(S,S),(0,0,0,0)), im))

def photo_card(img, w, h, frame_col, frame=34, r=60):
    card=Image.new('RGBA',(w,h),(0,0,0,0))
    m=rr_mask((w,h),r); fill=Image.new('RGBA',(w,h),frame_col+(255,)); card.paste(fill,(0,0),m)
    iw,ih=w-2*frame,h-2*frame
    pic=img.resize((iw,ih),Image.LANCZOS).convert('RGBA')
    card.paste(pic,(frame,frame),rr_mask((iw,ih),max(8,r-frame)))
    return card
def scenery(col, w=600, h=480):
    a=Image.new('RGB',(w,h)); a.paste(grad((w,h),tuple(int(c*0.55) for c in col),(12,16,34)))
    d=ImageDraw.Draw(a); d.ellipse((w*0.62,h*0.14,w*0.8,h*0.36),fill=(255,226,150))
    d.polygon([(0,h),(w*0.32,h*0.42),(w*0.55,h*0.75),(w*0.72,h*0.52),(w,h)],fill=col)
    return a
def place(card, cx, cy, angle):
    global canvas
    c=card.rotate(angle, resample=Image.BICUBIC, expand=True)
    shadow=Image.new('RGBA',c.size,(0,0,0,0)); shadow.putalpha(c.split()[3].point(lambda v:int(v*0.55)))
    shadow=shadow.filter(ImageFilter.GaussianBlur(22))
    layer=Image.new('RGBA',(S,S),(0,0,0,0))
    layer.paste(shadow,(int(cx-c.width/2+14),int(cy-c.height/2+30)),shadow)
    layer.paste(c,(int(cx-c.width/2),int(cy-c.height/2)),c)
    canvas=Image.alpha_composite(canvas,layer)

# back photos (other pictures being sorted)
place(photo_card(scenery(ORANGE),560,460,(255,214,170)), 1300, 730, -16)
place(photo_card(scenery(BLUE),560,460,(190,225,255)), 748, 730, 14)
# front photo: the Shadow
face=logo.crop((110,40,600,560))
place(photo_card(face,600,640,(236,244,255),frame=30), 1024, 790, 0)

# folder pocket in front (blue -> orange like the "=" key on ShadowCalc)
fx0,fy0,fx1,fy1=430,1080,1618,1640
folder=Image.new('RGBA',(S,S),(0,0,0,0))
fm=Image.new('L',(S,S),0); fd=ImageDraw.Draw(fm)
fd.rounded_rectangle((fx0,fy0,fx1,fy1),radius=110,fill=255)
fg=Image.new('RGB',(S,S)); _d=ImageDraw.Draw(fg)
for x in range(fx0,fx1+1):
    t=(x-fx0)/(fx1-fx0); u=min(1,max(0,(t-0.38)/0.24)); u=u*u*(3-2*u)
    _d.line([(x,0),(x,S)],fill=tuple(int(BLUE[k]+(ORANGE[k]-BLUE[k])*u) for k in range(3)))
# subtle vertical shading
shade=Image.new('RGB',(S,S),(255,255,255)); shade.paste(grad((S,fy1-fy0),(255,255,255),(185,185,200)),(0,fy0)); fg=ImageChops.multiply(fg,shade)
folder.paste(fg,(0,0),fm)
fsh=Image.new('L',(S,S),0); ImageDraw.Draw(fsh).rounded_rectangle((fx0,fy0-18,fx1,fy0+60),radius=60,fill=120)
fsh=fsh.filter(ImageFilter.GaussianBlur(26))
canvas=Image.alpha_composite(canvas,folder)
fdraw=ImageDraw.Draw(canvas)
# top highlight on the folder lip
# sort lines (three bars getting shorter = sorting)
cx=1024; y=1250
for i,wd in enumerate((500,360,220)):
    fdraw.rounded_rectangle((cx-wd/2,y+i*112,cx+wd/2,y+i*112+58),radius=29,fill=(255,255,255,235))
canvas=canvas.resize((1024,1024),Image.LANCZOS)
canvas.save(__import__('os').path.join(__import__('os').path.dirname(__file__),'icon.png'))
sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
canvas.save(__import__('os').path.join(__import__('os').path.dirname(__file__),'icon.ico'),sizes=sizes)
