"""Pixel Art presets without anyone else's names (NomadStudio#35).

The OPENHIKER source names games, consoles and companies in the group and
style labels AND inside the prompts (e.g. "Day of the Tentacle LucasArts, ...").
Styling is a paid pack, so every label and prompt is rewritten here as a plain
description of the look: era, hardware class, palette, genre, mood. Nothing
from the source text survives except the shared pixel-art suffix.

GROUPS: (source group label, new label {lang}, [(source style label,
new label {lang}, new prompt), ...]). apply() swaps them in place; TEXTS feeds
the package's i18n (labels are translated by their English text).
"""

SUFFIX = "sharp pixels, no antialiasing, limited color palette, pixel perfect, retro aesthetic"


def _l(en, es, zh, ko):
    return {"en": en, "es": es, "zh": zh, "ko": ko}


GROUPS = [
    ("8-bit Home Computers", _l("8-bit Home Computers", "Ordenadores domésticos de 8 bits", "8 位家用电脑", "8비트 가정용 컴퓨터"), [
        ("ZX Spectrum", _l("Attribute Clash, 15 Colours", "Choque de atributos, 15 colores", "属性冲突，15 色", "속성 충돌, 15색"),
         "1980s British 8-bit home computer pixel art, 15 bright colours on black, attribute colour clash, 256x192 resolution"),
        ("Commodore 64", _l("Muted 16-Colour Multicolour", "Multicolor apagado de 16 colores", "柔和 16 色多彩模式", "차분한 16색 멀티컬러"),
         "1980s 8-bit home computer pixel art, 16 muted colours, wide double-width multicolour pixels, browns and lilac tones"),
        ("Amstrad CPC", _l("Vivid 27-Colour Chunky Pixels", "27 colores vivos, píxel grueso", "鲜艳 27 色粗像素", "선명한 27색 굵은 픽셀"),
         "1980s European 8-bit home computer pixel art, vivid 27-colour palette, chunky wide pixels, saturated bright colours"),
        ("Atari 8-bit", _l("256-Colour Bands", "Franjas de 256 colores", "256 色色带", "256색 컬러 밴드"),
         "early 1980s American 8-bit home computer pixel art, 256-colour palette, horizontal colour bands, smooth colour gradients"),
        ("MSX", _l("Japanese 8-bit Computer", "Ordenador japonés de 8 bits", "日本 8 位电脑", "일본 8비트 컴퓨터"),
         "1980s Japanese 8-bit home computer pixel art, clean bright sprites, black backgrounds, arcade-like colours"),
    ]),
    ("16-bit Computers", _l("16-bit Computers", "Ordenadores de 16 bits", "16 位电脑", "16비트 컴퓨터"), [
        ("Commodore Amiga", _l("Painted Dither, 16-bit", "Tramado pintado, 16 bits", "手绘抖动，16 位", "페인팅 디더, 16비트"),
         "late 1980s 16-bit home computer pixel art, hand-painted dithered gradients, deep shading, moody European game art"),
        ("Atari ST", _l("16-bit Demoscene", "Demoscene de 16 bits", "16 位演示场景", "16비트 데모신"),
         "1980s 16-bit computer pixel art, 512-colour palette, low resolution, European demoscene look, metallic gradients"),
        ("PC EGA", _l("16-Colour Early PC", "PC antiguo de 16 colores", "早期 PC 16 色", "초기 PC 16색"),
         "early PC game pixel art, fixed 16-colour palette, cyan and magenta accents, heavy dithering"),
        ("PC VGA", _l("256-Colour 90s PC", "PC de los 90, 256 colores", "90 年代 PC 256 色", "90년대 PC 256색"),
         "1990s PC game pixel art, 256-colour palette, smooth shading, painted backgrounds"),
    ]),
    ("LucasArts Adventures", _l("Point-and-Click Adventures", "Aventuras point-and-click", "点击式冒险", "포인트 앤 클릭 어드벤처"), [
        ("Monkey Island Series", _l("Pirate Comedy Adventure", "Aventura cómica de piratas", "海盗喜剧冒险", "해적 코미디 어드벤처"),
         "early 1990s point-and-click adventure pixel art, Caribbean pirate comedy, moonlit tropical backgrounds, 256-colour painted scenes, cartoon characters"),
        ("Day of the Tentacle", _l("Squash-and-Stretch Cartoon Adventure", "Aventura cartoon elástica", "夸张卡通冒险", "과장된 카툰 어드벤처"),
         "1990s cartoon point-and-click adventure pixel art, exaggerated squash-and-stretch characters, skewed perspective backgrounds, saturated colours"),
        ("Maniac Mansion", _l("Spooky Mansion Adventure", "Aventura en mansión siniestra", "诡异豪宅冒险", "으스스한 저택 어드벤처"),
         "1980s point-and-click adventure pixel art, creepy old mansion, small chunky characters, limited 16-colour palette, comedic horror"),
        ("Indiana Jones and the Last Crusade", _l("Pulp Archaeology Adventure", "Aventura arqueológica pulp", "通俗考古冒险", "펄프 고고학 어드벤처"),
         "1980s pulp archaeology point-and-click adventure pixel art, ancient ruins and temples, explorer in a fedora, dusty earth tones"),
        ("Sam & Max Hit the Road", _l("Comic-Strip Road Trip Adventure", "Aventura de viñeta en carretera", "漫画公路冒险", "코믹 스트립 로드 트립 어드벤처"),
         "1990s comic-strip point-and-click adventure pixel art, bold outlines, absurd road-trip humour, bright flat colours"),
    ]),
    ("Sierra On-Line", _l("Painted Adventure Games", "Aventuras de fondos pintados", "手绘背景冒险游戏", "페인팅 배경 어드벤처"), [
        ("King's Quest Series", _l("Fairy-Tale Kingdom Adventure", "Aventura de reino de cuento", "童话王国冒险", "동화 왕국 어드벤처"),
         "1980s fairy-tale adventure game pixel art, castles and enchanted forests, detailed hand-painted 16-colour backgrounds, tiny characters"),
        ("Space Quest Series", _l("Sci-Fi Comedy Adventure", "Aventura cómica de ciencia ficción", "科幻喜剧冒险", "SF 코미디 어드벤처"),
         "early 1990s sci-fi comedy adventure pixel art, alien planets and starships, rich 256-colour environments"),
        ("Leisure Suit Larry", _l("Nightlife Comedy Adventure", "Aventura cómica nocturna", "夜生活喜剧冒险", "나이트라이프 코미디 어드벤처"),
         "late 1980s comedy adventure game pixel art, neon nightlife, casinos and bars, cartoonish characters"),
        ("Police Quest", _l("Police Procedural Adventure", "Aventura policial", "警察办案冒险", "경찰 수사 어드벤처"),
         "late 1980s police procedural adventure pixel art, city streets, patrol cars, realistic proportions"),
        ("Quest for Glory", _l("Fantasy Hero RPG Adventure", "Aventura RPG de héroe fantástico", "奇幻英雄 RPG 冒险", "판타지 영웅 RPG 어드벤처"),
         "early 1990s fantasy role-playing adventure pixel art, hero in a valley town, painted landscapes"),
    ]),
    ("Nintendo 8-bit & 16-bit", _l("8- & 16-bit Console Classics", "Clásicos de consola de 8 y 16 bits", "8/16 位主机经典", "8·16비트 콘솔 클래식"), [
        ("Super Mario Bros / World", _l("Bright Side-Scrolling Platformer", "Plataformas lateral luminoso", "明亮横版平台", "밝은 횡스크롤 플랫포머"),
         "16-bit console side-scrolling platformer pixel art, bright rounded hills, floating blocks, cheerful saturated colours"),
        ("The Legend of Zelda", _l("Top-Down Adventure Quest", "Aventura cenital", "俯视角冒险", "탑다운 모험"),
         "8-bit console top-down action adventure pixel art, overworld map tiles, small hero sprite, forests and dungeons"),
        ("Metroid", _l("Sci-Fi Cavern Exploration", "Exploración de cavernas sci-fi", "科幻洞穴探索", "SF 동굴 탐험"),
         "8-bit and 16-bit console sci-fi exploration pixel art, armoured space explorer, alien caverns, dark blues and purples"),
        ("Mega Man", _l("Robot Action Platformer", "Plataformas de acción robótica", "机器人动作平台", "로봇 액션 플랫포머"),
         "8-bit console robot action platformer pixel art, small robot hero, flat bright colours, black outlines, boss stages"),
        ("Castlevania", _l("Gothic Horror Platformer", "Plataformas de terror gótico", "哥特恐怖平台", "고딕 호러 플랫포머"),
         "8-bit and 16-bit gothic horror platformer pixel art, castle corridors, candles, monster hunters, deep reds and purples"),
        ("Kirby", _l("Cute Pastel Platformer", "Plataformas pastel adorable", "可爱粉彩平台", "귀여운 파스텔 플랫포머"),
         "cute console platformer pixel art, round pastel characters, soft pink and sky blue, dreamy clouds"),
        ("Donkey Kong Country", _l("Pre-Rendered Jungle Platformer", "Plataformas selvático prerrenderizado", "预渲染丛林平台", "프리렌더 정글 플랫포머"),
         "mid-1990s 16-bit console platformer pixel art, pre-rendered 3D look sprites, lush jungle, rich shading"),
    ]),
    ("Arcade Classics", _l("Arcade Classics", "Clásicos de recreativa", "街机经典", "아케이드 클래식"), [
        ("Metal Slug Series", _l("Military Mecha Arcade", "Recreativa militar con mechas", "军事机甲街机", "밀리터리 메카 아케이드"),
         "late 1990s arcade run-and-gun pixel art, ultra detailed hand-drawn soldiers and tanks, chunky military vehicles, explosions"),
        ("Street Fighter II", _l("16-bit Arcade Fighter", "Lucha arcade de 16 bits", "16 位街机格斗", "16비트 아케이드 격투"),
         "early 1990s arcade fighting game pixel art, large detailed fighters, stage backgrounds, bold shading"),
        ("Final Fight", _l("Urban Beat 'em Up", "Beat 'em up urbano", "都市清版格斗", "도시 벨트스크롤 액션"),
         "early 1990s arcade beat 'em up pixel art, gritty city streets, large brawler characters"),
        ("Pac-Man", _l("Maze Arcade", "Recreativa de laberinto", "迷宫街机", "미로 아케이드"),
         "early 1980s maze arcade game pixel art, glowing dots on black, simple bright sprites"),
        ("Galaga / Galaxian", _l("Space Shooter Arcade", "Matamarcianos de recreativa", "太空射击街机", "우주 슈팅 아케이드"),
         "early 1980s arcade space shooter pixel art, insect-like alien formations, starfield on black"),
        ("1942 / 1943", _l("WWII Plane Shooter", "Shooter de aviones de la 2.ª GM", "二战飞机射击", "2차대전 비행기 슈팅"),
         "1980s vertical scrolling WWII plane shooter pixel art, top-down aircraft over the ocean"),
        ("Ghosts 'n Goblins", _l("Knight vs Monsters Platformer", "Plataformas caballero contra monstruos", "骑士大战怪物平台", "기사 대 괴물 플랫포머"),
         "1980s arcade dark fantasy platformer pixel art, armoured knight, graveyards, zombies and demons"),
    ]),
    ("Run & Gun / Shooters", _l("Run & Gun / Shooters", "Run & gun / shooters", "跑射 / 射击", "런앤건 / 슈팅"), [
        ("Contra / Probotector", _l("Commando Run & Gun", "Run & gun de comandos", "突击队跑射", "코만도 런앤건"),
         "late 1980s run-and-gun pixel art, commandos in jungles and alien bases, intense action"),
        ("Gunstar Heroes", _l("Hyperkinetic Run & Gun", "Run & gun frenético", "高速跑射", "초고속 런앤건"),
         "16-bit console run-and-gun pixel art, colourful explosions, fast dynamic action, bright anime-style characters"),
        ("Blazing Chrome", _l("Neo-Retro Robot War", "Guerra robótica neorretro", "新复古机器人战争", "네오레트로 로봇 전쟁"),
         "modern retro run-and-gun pixel art, robot war, detailed sprites, gritty sci-fi"),
        ("Cuphead", _l("1930s Rubber-Hose Cartoon", "Cartoon de manguera de los años 30", "1930 年代橡皮管卡通", "1930년대 러버호스 카툰"),
         "1930s rubber hose cartoon pixel art, pie-cut eyes, bouncy limbs, sepia film tones"),
        ("Risky Woods", _l("Dark Fantasy Forest", "Bosque de fantasía oscura", "黑暗奇幻森林", "다크 판타지 숲"),
         "early 1990s 16-bit computer dark fantasy pixel art, detailed monsters, gloomy forests"),
    ]),
    ("Sega & Other 16-bit", _l("16-bit Console Era", "Era de consolas de 16 bits", "16 位主机时代", "16비트 콘솔 시대"), [
        ("Sega Genesis / Mega Drive", _l("Vibrant Parallax 16-bit", "16 bits vibrante con parallax", "鲜艳视差 16 位", "선명한 패럴랙스 16비트"),
         "16-bit console pixel art, vibrant high-contrast colours, parallax scrolling layers"),
        ("Sonic the Hedgehog", _l("High-Speed Loop Platformer", "Plataformas de alta velocidad", "高速环道平台", "고속 루프 플랫포머"),
         "16-bit high-speed platformer pixel art, rolling hills, loops and ramps, bright blue skies"),
        ("Shinobi", _l("Ninja Action", "Acción ninja", "忍者动作", "닌자 액션"),
         "16-bit ninja action pixel art, shuriken, night city rooftops"),
        ("Golden Axe", _l("Barbarian Beat 'em Up", "Beat 'em up de bárbaros", "野蛮人清版格斗", "바바리안 벨트스크롤 액션"),
         "16-bit fantasy beat 'em up pixel art, barbarians and dwarves with axes, mounted beasts"),
        ("Streets of Rage", _l("Neon City Beat 'em Up", "Beat 'em up de ciudad neón", "霓虹都市清版格斗", "네온 도시 벨트스크롤 액션"),
         "16-bit beat 'em up pixel art, neon city at night, street brawlers, detailed characters"),
    ]),
    ("Other Classic Consoles & Styles", _l("Other Classic Styles", "Otros estilos clásicos", "其他经典风格", "기타 클래식 스타일"), [
        ("Game Boy", _l("4-Shade Green Handheld", "Portátil de 4 verdes", "四阶绿色掌机", "4단계 녹색 휴대용"),
         "early handheld console pixel art, 4 shades of green, monochrome, low resolution"),
        ("Neo-Geo", _l("Large-Sprite Arcade", "Recreativa de sprites grandes", "大精灵街机", "대형 스프라이트 아케이드"),
         "1990s arcade pixel art, large high-resolution sprites, detailed fighters"),
        ("PC-Engine / TurboGrafx", _l("Bright Japanese Console", "Consola japonesa luminosa", "明亮的日本主机", "밝은 일본 콘솔"),
         "late 1980s Japanese console pixel art, vibrant colours, shoot 'em up energy"),
        ("Isometric Pixel Art", _l("Isometric Pixel Art", "Pixel art isométrico", "等距像素艺术", "아이소메트릭 픽셀 아트"),
         "isometric pixel art, 45 degree angle, detailed tiles"),
        ("Dithering Heavy", _l("Dithering Heavy", "Tramado intenso", "重度抖动", "강한 디더링"),
         "heavy dithering pixel art, gradient simulation with dots"),
    ]),
    ("Modern Retro Inspirations", _l("Modern Indie Pixel Art", "Pixel art indie moderno", "现代独立像素艺术", "모던 인디 픽셀 아트"), [
        ("Celeste", _l("Mountain Climb Platformer", "Plataformas de escalada", "登山平台", "등산 플랫포머"),
         "modern indie platformer pixel art, snowy mountain, soft purple and pink palette, small precise character"),
        ("Shovel Knight", _l("8-bit Revival Knight", "Caballero revival 8 bits", "8 位复兴骑士", "8비트 리바이벌 기사"),
         "modern 8-bit revival pixel art, armoured knight hero, limited 8-bit console palette"),
        ("Hyper Light Drifter", _l("Neon Ruin Wanderer", "Vagabundo entre ruinas neón", "霓虹废墟漫游者", "네온 폐허 방랑자"),
         "modern indie pixel art, mysterious ruins, neon magenta and teal, lone wanderer, atmospheric"),
        ("Dead Cells", _l("Fluid Roguelike Action", "Acción roguelike fluida", "流畅 Roguelike 动作", "유려한 로그라이크 액션"),
         "modern roguelike action pixel art, fluid animation, dark castle dungeons, glowing accents"),
    ]),
]

COUNT = sum(len(styles) for _, _, styles in GROUPS)

# English text -> {es, zh, ko}, for the package i18n ("_texts").
TEXTS = {}
for _, glabel, styles in GROUPS:
    TEXTS[glabel["en"]] = {k: v for k, v in glabel.items() if k != "en"}
    for _, slabel, _ in styles:
        TEXTS[slabel["en"]] = {k: v for k, v in slabel.items() if k != "en"}


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")


def apply(flow: dict) -> dict:
    """Replace the source's groups/styles in a Pixel Art flow. Fails loudly if
    the source changed (a group or style this table doesn't know)."""
    by_group = {src: (lab, {s: (l, p) for s, l, p in styles}) for src, lab, styles in GROUPS}
    done = 0

    def walk(node):
        nonlocal done
        if isinstance(node, dict):
            if isinstance(node.get("groups"), list) and node.get("type") == "compose":
                for g in node["groups"]:
                    lab, styles = by_group[g["label"]]
                    g["id"], g["label"] = _slug(lab["en"]), lab["en"]
                    for opt in g["options"]:
                        new_label, prompt = styles[opt["label"]]
                        opt["label"], opt["value"] = new_label["en"], f"{prompt}, {SUFFIX}"
                        done += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(flow)
    if done != COUNT:
        raise ValueError(f"Pixel Art: rewrote {done} styles, table has {COUNT}")
    return flow
