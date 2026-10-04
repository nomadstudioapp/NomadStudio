"""Vintage looks — 69 one-click retro presets folded into Photo Editing as 4
flows, one per family (build_packages._vintage_flows). Free and bundled with
the app. Preset labels and prompts are our own wording; prompts stay in
English because they go straight to the edit model.

Each family: (flow slug, card label/desc in the 4 languages, tags, presets).
"""

KEEP = " Keep the subject, pose and composition recognizable."

SIGNAL = [
    {"label": "Tube Monitor", "text": "Display the image on a curved 1980s cathode-ray monitor, shot head-on: fine RGB aperture-grille mask, phosphor glow blooming around bright areas, bulging barrel distortion with rounded screen corners, darker glass edges, deep blacks and faint horizontal scanlines." + KEEP},
    {"label": "Worn Videotape", "text": "Turn it into a paused frame from an old, much-played videotape: soft smeary resolution, colors bleeding to the side, a strip of tracking noise ripping along the bottom, thin white dropout lines, a slight tape-crease wobble, faded warm-magenta color and analog snow." + KEEP},
    {"label": "Analog Broadcast", "text": "Show it as an over-the-air analog TV picture: color smearing past the edges, ringing halos around contrast lines, crawling dots on sharp edges, a slightly mistuned hue, light static and the overly saturated, slightly wrong colors of an old tube set." + KEEP},
    {"label": "1-Bit Pixels", "text": "Convert it into an early-90s computer graphic: strict ordered dithering with a tiny color palette, chunky visible pixels, every gradient and shadow built from crisp dither patterns, like an image opened on an early desktop computer." + KEEP},
    {"label": "Phosphor Terminal", "text": "Show it on a monochrome green-phosphor computer terminal: the whole picture in glowing greens on black, strong horizontal scanlines, soft phosphor glow, a faint persistence smear and the dark curved edge of the screen bezel." + KEEP},
    {"label": "RGB Fringe", "text": "Add heavy lens chromatic aberration: red, green and blue channels split and pushed outward from the center, colored fringes along every edge and slightly soft corners, like a cheap old lens." + KEEP},
    {"label": "Dream Glow", "text": "Give it an 80s glamour-lens glow: highlights spilling into a soft luminous halo, diffusion glow on skin and lights, lifted blacks, warm pastel color and a dreamy soft focus." + KEEP},
    {"label": "Data Corruption", "text": "Corrupt it like a broken digital video file: rectangular blocks shoved sideways, repeated and smeared slices, color channels drifting in horizontal bands and compression artifacts, with the main subject still readable."},
    {"label": "Signal Drift", "text": "Distort it like an interrupted analog broadcast: smooth wavy horizontal displacement, rolling interference bands, drifting and partly washed-out color, soft static over the whole frame." + KEEP},
    {"label": "Dial-Up Webcam", "text": "Make it look like a mid-90s webcam call frame: very low resolution scaled up into blocky pixels, early codec quantization squares, a small noisy dithered palette and slightly smeared motion." + KEEP},
    {"label": "Glyph Rain", "text": "Rebuild the whole image from vertical columns of falling glowing green characters on black, the brightness of the glyphs tracing the shapes and lighting of the photo so the subject stays clearly recognizable, bright lead characters and fading trails."},
    {"label": "Tube Shutdown", "text": "Capture an old CRT television at the instant it switches off: the picture squeezed into a bright horizontal band across a dark screen, a white-hot core line, soft phosphor glow and curved dark glass around it, the photo still faintly visible inside the band."},
]

PRINT = [
    {"label": "Poster Bands", "text": "Posterize it into a handful of flat bold color bands with hard edges between tones, no gradients, graphic high-contrast light and shadow, like a screen-printed concert poster." + KEEP},
    {"label": "Pop Dots", "text": "Turn it into a 1960s pop-art print: thick black ink outlines, flat saturated primaries, visible halftone dots in the shading and a bright solid background color, loud and graphic." + KEEP},
    {"label": "Newsprint Comic", "text": "Redraw it as a vintage comic-book panel printed on yellowed newsprint: inked line art, limited four-color palette, slightly misregistered color plates, halftone texture and aged paper grain, with no speech balloons and no lettering." + KEEP},
    {"label": "Seventies Spread", "text": "Make it look like a photo printed in a 1970s magazine: warm faded color, heavy grain, soft contrast, slightly yellowed paper with a visible print screen, amber and olive tones." + KEEP},
    {"label": "Two-Ink Riso", "text": "Print it as a two-color risograph: fluorescent pink and teal inks, grainy stippled texture, layers slightly out of register, visible paper tooth and flat overlapping ink shapes." + KEEP},
]

FILM = [
    {"label": "Old Reel", "text": "Make it look like a frame shot on old analog film: fine organic grain, a few dust specks and thin vertical scratches, softly faded blacks with gentle halation, a cinematic teal-and-amber grade, slightly soft edges and a light vignette." + KEEP},
    {"label": "Blown Out", "text": "Make it look like an overexposed vintage film photo: creamy blown highlights, washed-out low-contrast shadows, a warm yellow-peach cast, soft bloom around bright areas and fine grain." + KEEP},
    {"label": "Leaky Camera", "text": "Add real analog light leaks: warm orange, red and magenta glows creeping in from the frame edges and across part of the picture, soft haze where the leak lands, fine grain and slightly faded contrast." + KEEP},
    {"label": "Reel End Burn", "text": "Add a film burn: one edge of the frame melting into a hot orange-white glow with darker scorched falloff, warm flare spilling into the image, grain and faded color like the last frames of a reel." + KEEP},
    {"label": "Pushed Grain", "text": "Render it as film pushed to high ISO: coarse, clearly visible organic grain everywhere, rich deep blacks, slightly muted color and natural film tonality." + KEEP},
    {"label": "Instant Print", "text": "Make it look like a vintage instant-camera print: soft focus, low-contrast faded color with cyan-green shadows and creamy highlights, uneven chemistry near the edges and a gentle vignette, with no white border and no writing." + KEEP},
    {"label": "Home Movie", "text": "Make it look like a frame from a 1970s small-gauge home movie: heavy grain, warm saturated faded color, soft focus, a slight gate-weave blur, a dark rounded frame edge, dust and hair specks." + KEEP},
    {"label": "Wrong Chemistry", "text": "Cross-process it like slide film developed in the wrong chemicals: punchy contrast, yellow-green highlights, cyan-blue shadows and oversaturated, shifted colors with grain." + KEEP},
    {"label": "Tin Plate", "text": "Turn it into an antique 19th-century tintype: warm sepia-brown monochrome, shallow soft focus falloff, a silvery metallic sheen, uneven chemical edges, fine scratches and a dark vignette." + KEEP},
    {"label": "Sun Print", "text": "Turn it into a lumen print, a camera-less photogram made by leaving the subject on photographic paper in the sun: shapes glowing as soft luminous silhouettes in warm versions of the photo's own colors against deep dark paper, translucent edges, fine veins and ghostly inner detail, faint chemical stains."},
    {"label": "Light Trails", "text": "Make it look like a long exposure lit by a moving light in a dark room: the subject glowing in soft luminous color, doubled and smeared by gentle camera motion, bright cores fading into translucent trails, a deep dark background, dreamy and painterly."},
]

COLLAGE = [
    {"label": "Speckle Duotone", "text": "Reprint it as a grainy two-ink stipple duotone: the subject in deep navy and cyan speckle with fine horizontal scanline texture, a soft mustard-yellow glow around the silhouette, on cream paper dusted with ochre grain."},
    {"label": "Fluted Glass", "text": "Cut the image into tall vertical strips and distort each one differently: wavy liquid ripples, stretched and smeared pixels, strips sliding up and down against each other with dark gaps between some of them, like looking through fluted glass."},
    {"label": "Pen Hatching", "text": "Redraw it in black and white using only dense scribbled horizontal and diagonal pen hatching, like a photocopied etching: tones built purely from line density, gritty copier texture, deep blacks and paper-white highlights."},
    {"label": "Burnt Dub", "text": "Blow it out like a burned, oversaturated tape copy: magenta and electric green bleeding everywhere, crushed noisy color speckle, smeared edges, a slight fisheye bulge and wavy interference in the bright areas."},
    {"label": "Twin Exposure", "text": "Turn it into a monochrome in-camera double exposure: the subject's silhouette filled with a second image of bare branches and a hazy city skyline, soft translucent overlap, misty grey tones and gentle light leaks."},
    {"label": "Frosted Pane", "text": "Put everything behind a sheet of frosted glass: soft diffused blur, colors reduced to one cool tint, only the parts touching the glass a little sharper, milky white glow around the edges, quiet and ghostly."},
    {"label": "Cobalt Fog", "text": "Make it look like an underexposed 35mm photo taken in thick blue-hour fog: everything drowned in deep cobalt, lifted grainy shadows, haze swallowing the background, a few small warm lights glowing through, dust specks."},
    {"label": "Dust Scatter", "text": "Render the subject from swirling fingerprint-like line texture, one side of the figure breaking apart into scattered particles, ink splatter and fine flying fragments, on a clean light background."},
    {"label": "Diamond Shards", "text": "Make it a black-and-white halftone print cut into diamond-shaped pieces: the lower part intact, the upper part coming apart into paper diamonds drifting upward, white gaps where pieces are missing, real paper texture."},
    {"label": "Scanner Drag", "text": "Make it a faded photocopied vintage print with a scanner-drag smear: one region stretched sideways into mint-cyan streaks, dusty copier texture and a thin light-blue scan line crossing the frame."},
    {"label": "Lost Signal", "text": "Show it on a failing analog TV: the upper part of the frame dissolving into horizontal RGB interference bands and blocky sync noise while the lower part stays readable, heavy screen-dot texture and color fringing."},
    {"label": "Heat Camera", "text": "Recolor it as a noisy thermal-camera image: hot pink and soft lime-green palette, the subject a dark grainy mass, heavy speckled pixel noise over the whole frame, low resolution."},
    {"label": "Screen Ghost", "text": "Turn it into a glowing ghost on a dark CRT: the subject made of luminous electric blue and white light with a visible screen pixel mesh, the face dissolving into dark static with streaks of green signal noise, bloom around the glow."},
    {"label": "Scanline Relief", "text": "Rebuild it from glowing horizontal scan lines on black, like an analog video synthesizer: bright cyan-blue lines bending over the subject's contours to form a 3D relief, some lines breaking into dots at the edges."},
    {"label": "Melting Display", "text": "Show it on a close-up pixel display where the picture melts: a dark silhouette with glowing blue and violet halos, dripping and rippling vertical light trails, a visible LED subpixel grid and deep blacks."},
    {"label": "Number Silhouette", "text": "Turn the subject into a silhouette made only of white monospace digits, braces and percent signs on a grid, some glyphs in white outlined boxes and some in filled white boxes, a few tiny pink and cyan bracket accents, on a flat saturated electric-blue background, nothing else."},
    {"label": "Teletext Page", "text": "Re-render it as a low-resolution teletext screen: every area filled with repeating bitmap patterns instead of shading, rows of yellow dots in bright areas, periwinkle vertical stripes in mid-tones, tiny white glyph dots, dark shapes kept as solid silhouettes, harsh palette of yellow, orange, lavender and black."},
    {"label": "Marker Rows", "text": "Redraw the whole image by hand with felt-tip pens strictly row by row in horizontal strokes: every tone built from parallel marker lines in slightly brightened colors from the photo, with wobble, gaps and overlaps, streaky ink where a pen runs dry, ragged line ends and white paper showing between strokes."},
    {"label": "Melted Emulsion", "text": "Make it a sepia darkroom print whose emulsion has melted: bleach splashes and liquid streaks tearing across the image, solarized edges, small bubble rings and droplets, glossy burned-out white trails, the subject partly dissolved but still readable."},
    {"label": "Oil Pastel", "text": "Redraw it freehand in crude oil pastel and acrylic on a dark canvas, on purpose imperfect: wobbly outlines, loose scribbled fills in a few bold colors from the photo that overlap and spill outside their shapes, uneven pressure, smudges and bare patches of canvas, expressive rather than accurate."},
    {"label": "Flat Brush", "text": "Repaint the subject as a loose alla-prima oil painting of wide flat-brush strokes, each one a single confident swipe with bristle drag and dry broken edges, following the planes of the body and clothes. Keep the face minimal, just a few flat planes of light and shadow. Leave large areas of raw white canvas around the figure, in a restrained palette of a few earthy tones from the photo."},
    {"label": "Warning Stripes", "text": "Replace the subject with a flat cut-paper silhouette printed with bold diagonal black and acid-yellow warning stripes, glued onto a scratched, weathered olive-green board, with rough torn edges and faint scuffs."},
    {"label": "Scrapbook", "text": "Turn it into a mixed-media collage: the subject as a desaturated black-and-white photo cutout covered with torn paper, painted paper, burlap and fabric patches and halftone fragments layered over most of the face, leaving only one or two features such as an eye and the lips visible, on a loosely brushed painted background in a few muted tones that suit the photo."},
    {"label": "Painted Paper", "text": "Recreate the subject as an angular cut-paper silhouette assembled from a few hand-painted sheets with crisp faceted edges: face, hair and clothing each cut from a differently colored sheet taken from or complementing the photo, dry-brushed dark marks for the features, one sheet torn roughly, on a plain warm-white background."},
    {"label": "Running Watercolor", "text": "Use the photo only for pose and features and paint a fully new watercolor on white cold-press paper: head and neck filled with rich saturated washes in two or three colors from the photo bleeding together, pigment running down in long drips that carve pale channels, granulation and dark tide-line edges, the eyes fairly clear while nose and mouth smear away, plenty of untouched white paper around."},
    {"label": "Shape Collage", "text": "A single head, never duplicated: cut it into 6 to 8 irregular photo fragments and pull them apart so the face breaks and its proportions change, one piece enlarged, one rotated, one slid sideways with a motion-blur trail. Fill the gaps with flat geometric shapes in a palette that complements the photo, each with its own hand-drawn pattern, layered with soft drop shadows and thin connecting lines on a paper ground, still reading as one face."},
    {"label": "Doodled Photo", "text": "Keep the image as a photographic scan and scribble over it: fast, loose marker and ballpoint lines in pink, magenta, cyan, purple and yellow, dense in some areas and sparse in others, a few details traced in black ink, the photo underneath clearly visible everywhere and never turned into a drawing."},
    {"label": "Copier Collage", "text": "Turn it into a grainy sepia photocopy collage: the subject blurred and overexposed, with torn paper strips, blueprint fragments, a barcode strip and blurred typed scraps layered on top, heavy toner noise and paper texture."},
    {"label": "Cut-Up Halftone", "text": "Reprint the image as a harsh black-and-white copier halftone with coarse dots and blown whites, then cut the face into rectangular and irregular fragments reassembled out of line: features offset, one eye repeated at another scale, the mouth enlarged and shifted, hard straight cuts and lots of white paper around."},
    {"label": "Dot Wedge", "text": "Make it a grainy monochrome print: the subject in soft dark stipple, crossed by one large sharp-edged geometric wedge where the same image is reprinted in very coarse round halftone dots at another angle and scale, plus a small offset triangle of the shoulder, clean white paper around."},
    {"label": "Solar Streaks", "text": "Invert and solarize the image into a stark two-tone print of one deep ink color on white, shadows turned to glowing white and highlights to dense ink, with violent horizontal light streaks dragged across the frame like a hand through wet emulsion, grainy edges."},
    {"label": "Broken Mirror", "text": "Show the face reflected in a shattered mirror: the image split into long sharp triangular shards, each slightly shifted, rotated and rescaled so features double and misalign, thin bright edges on every crack, all washed into one posterized monochrome tint from the photo."},
    {"label": "Side Smear", "text": "Keep most of the face photographic but drag one side of it sideways: skin, eye and features stretched into long smooth horizontal smears and wavy streaks running off the frame, like a pixel-sort drag, the rest intact, the whole image in one punchy monochrome hue."},
    {"label": "Ink Fade", "text": "Turn it into a black-and-white fine-art photo where the top of the head dissolves into white: loose looping ink scribbles, splatters and dry-brush marks replacing the eyes and hair, while nose, lips and jaw stay soft and photographic, grainy and airy with lots of white."},
    {"label": "Disk Wall", "text": "Rebuild the portrait as a wall of real 3.5-inch floppy disks laid flat in a tight grid, each disk printed with one piece of the portrait so together they form the whole face, metal shutters, blank labels, plastic edges and small gaps visible, disks in two or three plastic colors that suit the photo, moody low-key light, blank unreadable labels only."},
    {"label": "Cube Glitch", "text": "Break the face into hundreds of small rectangular blocks pushed forward, back and sideways by different amounts, like a 3D extrusion glitch: some blocks repeat an eye or eyebrow, the hairline breaks into jagged steps, grainy film texture on a pale plain background."},
    {"label": "Crushed Page", "text": "Make it a glossy magazine photo that was crumpled and flattened again: deep creases and folds across the face, parts of the page folded over so features shift and overlap, wrinkles catching the light, worn glossy sheen and slightly warm magazine color."},
    {"label": "Mask Layers", "text": "Build one head from many cut-out paper layers of the same face at different scales and angles, stacked like peeled masks, each showing part of the face such as lips, eyes, cheek or ear, pale tones with one bold lip color, clean paper edges and soft shadows on a flat dark background."},
    {"label": "Rainbow Ghosts", "text": "Make it a grainy riso-style print where the head is dragged sideways into soft ghost trails with rainbow fringes along the edges, the face dark and stippled, the body washed into pale bleeding pastels, black background above, grainy paper texture."},
    {"label": "Maze Lines", "text": "Posterize the face into a pale glowing shape on black and redraw its shading as tight maze-like contour lines, zigzags and spirals in thin pastel neon, with a few concentric geometric shapes and circuit-like lines floating in the dark."},
    {"label": "Millennium Collage", "text": "Turn it into a bold late-90s digital collage: the subject in smooth flat vector shading with a solid band over the eyes, a big flat sun disc behind the head, ornate patterned shapes framing the face, pixelated trees and rocks, an old beige computer monitor and a framed landscape photo on a flat saturated background."},
]

FAMILIES = [
    {
        "slug": "vintage_signal",
        "presets": SIGNAL,
        "tags": ["Vintage", "Screen", "Free"],
        "label": {"en": "Vintage — Signal & Screen", "es": "Vintage — Señal y pantalla",
                  "zh": "复古 — 信号与屏幕", "ko": "빈티지 — 신호와 화면"},
        "desc": {"en": "Tube monitors, worn tapes, analog TV, glitches and early-computer pixels.",
                 "es": "Monitores de tubo, cintas gastadas, TV analógica, glitches y píxeles de los primeros ordenadores.",
                 "zh": "显像管显示器、磨损录像带、模拟电视、故障效果和早期电脑像素。",
                 "ko": "브라운관 모니터, 낡은 비디오테이프, 아날로그 TV, 글리치와 초기 컴퓨터 픽셀."},
    },
    {
        "slug": "vintage_print",
        "presets": PRINT,
        "tags": ["Vintage", "Print", "Free"],
        "label": {"en": "Vintage — Pop & Print", "es": "Vintage — Pop e impresión",
                  "zh": "复古 — 波普与印刷", "ko": "빈티지 — 팝과 인쇄"},
        "desc": {"en": "Screen-print posters, pop-art dots, newsprint comics, 70s magazines and riso.",
                 "es": "Pósters serigrafiados, puntos pop-art, cómic en papel de periódico, revistas de los 70 y riso.",
                 "zh": "丝网海报、波普网点、报纸漫画、70 年代杂志和孔版印刷。",
                 "ko": "실크스크린 포스터, 팝아트 도트, 신문지 코믹, 70년대 잡지와 리소 인쇄."},
    },
    {
        "slug": "vintage_film",
        "presets": FILM,
        "tags": ["Vintage", "Film", "Free"],
        "label": {"en": "Vintage — Film & Darkroom", "es": "Vintage — Película y laboratorio",
                  "zh": "复古 — 胶片与暗房", "ko": "빈티지 — 필름과 암실"},
        "desc": {"en": "Old film stock, light leaks, burns, instant prints, home movies and tintypes.",
                 "es": "Película antigua, fugas de luz, quemados, fotos instantáneas, cine casero y ferrotipos.",
                 "zh": "老胶片、漏光、烧片、拍立得、家庭电影和锡版照片。",
                 "ko": "오래된 필름, 빛샘, 필름 번, 즉석 사진, 홈 무비와 틴타입."},
    },
    {
        "slug": "vintage_collage",
        "presets": COLLAGE,
        "tags": ["Vintage", "Collage", "Free"],
        "label": {"en": "Vintage — Collage & Experimental", "es": "Vintage — Collage y experimental",
                  "zh": "复古 — 拼贴与实验", "ko": "빈티지 — 콜라주와 실험"},
        "desc": {"en": "Paper collage, copier art, hand-drawn marks, screen ghosts and analog distortions.",
                 "es": "Collage de papel, arte de fotocopiadora, trazos a mano, fantasmas de pantalla y distorsiones analógicas.",
                 "zh": "纸张拼贴、复印艺术、手绘笔触、屏幕幻影和模拟失真。",
                 "ko": "종이 콜라주, 복사기 아트, 손그림 마크, 스크린 고스트와 아날로그 왜곡."},
    },
]

# UI strings of the vintage flows that the translation tables don't carry yet.
UI_TEXTS = {
    "Pick a vintage look, or write your own.": {
        "es": "Elige un look vintage, o escribe el tuyo.",
        "zh": "选择一种复古风格，或自己写。",
        "ko": "빈티지 룩을 고르거나 직접 작성하세요.",
    },
}
for _family in FAMILIES:
    UI_TEXTS[_family["desc"]["en"]] = {k: v for k, v in _family["desc"].items() if k != "en"}
