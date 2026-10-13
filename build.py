#!/usr/bin/env python3
"""Generate the Olamic Cutlery static preview in this directory.

    python3 build.py

Images are resized JPEGs composited on the page color. Sources stay in
the parent images-transparent and models folders.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).resolve().parent
IMG = ROOT / "images-transparent"
MODELS_DIR = ROOT / "models"

LINK = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")

SWIFT = r'''
import AppKit
import Foundation

let args = Array(CommandLine.arguments.dropFirst())
var i = 0
while i + 1 < args.count {
    let src = URL(fileURLWithPath: args[i])
    let dest = URL(fileURLWithPath: args[i + 1])
    i += 2
    guard let image = NSImage(contentsOf: src) else {
        fputs("FAIL \(src.path)\n", stderr)
        continue
    }
    var proposed = NSRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else {
        fputs("FAIL \(src.path)\n", stderr)
        continue
    }
    let maxEdge = 1500.0
    let scale = min(1.0, maxEdge / Double(max(cg.width, cg.height)))
    let w = max(1, Int((Double(cg.width) * scale).rounded()))
    let h = max(1, Int((Double(cg.height) * scale).rounded()))
    guard let ctx = CGContext(
        data: nil,
        width: w,
        height: h,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
    ) else { continue }
    ctx.setFillColor(CGColor(red: 243.0/255.0, green: 238.0/255.0, blue: 230.0/255.0, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.interpolationQuality = .high
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
    guard let out = ctx.makeImage() else { continue }
    let rep = NSBitmapImageRep(cgImage: out)
    guard let data = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.74]) else { continue }
    try data.write(to: dest)
    print("OK \(w) \(h) \(dest.path)")
}
'''


def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline(text: str, prefix: str) -> str:
    parts = []
    last = 0
    for match in LINK.finditer(text):
        parts.append(esc(text[last : match.start()]))
        label, href = match.group(1), match.group(2)
        if href.startswith("http"):
            url = href
            extra = ' rel="noopener noreferrer"'
        elif href.startswith("mailto:"):
            url = href
            extra = ""
        else:
            url = prefix + href
            extra = ""
        parts.append(f'<a href="{esc(url)}"{extra}>{esc(label)}</a>')
        last = match.end()
    parts.append(esc(text[last:]))
    return "".join(parts)


def paras(items, prefix: str) -> str:
    return "\n".join(f"<p>{inline(item, prefix)}</p>" for item in items)


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    i = 2
    while i + 8 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + length
    raise RuntimeError(f"no size in {path}")


def spread(files: list[Path], count: int) -> list[Path]:
    files = [path for path in files if path.suffix.lower() == ".png"]
    if len(files) <= count:
        return files
    indexes = [round(i * (len(files) - 1) / (count - 1)) for i in range(count)]
    chosen = []
    seen = set()
    for index in indexes:
        path = files[index]
        if path not in seen:
            chosen.append(path)
            seen.add(path)
    return chosen


def pick(folders, count=8, hero=None, window=None) -> list[Path]:
    files = []
    for folder in folders:
        folder = Path(folder)
        if not folder.exists():
            print(f"missing image folder: {folder}")
            continue
        files.extend(sorted(folder.glob("*.png")))
    if window:
        start, length = window
        chosen = files[start : start + length]
    else:
        chosen = spread(files, count)
    if hero:
        match = next((path for path in files if path.name == hero), None)
        if match is not None:
            chosen = [match] + [path for path in chosen if path != match]
            if window is None:
                chosen = chosen[:count]
    return chosen


def prepare_images(jobs: list[tuple[Path, Path]]) -> dict[Path, tuple[int, int]]:
    sizes = {}
    pending = []
    for src, dest in jobs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
            sizes[dest] = jpeg_size(dest)
        else:
            pending.append((src, dest))
    if not pending:
        return sizes
    script = Path("/tmp/olc-composite.swift")
    script.write_text(SWIFT)
    args = ["swift", str(script)]
    for src, dest in pending:
        args.extend([str(src), str(dest)])
    print(f"compositing {len(pending)} images")
    proc = subprocess.run(args, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-2000:] or proc.stdout[-2000:])
    made = set()
    for line in proc.stdout.splitlines():
        if not line.startswith("OK "):
            continue
        _, width, height, path = line.split(" ", 3)
        dest = Path(path)
        sizes[dest] = (int(width), int(height))
        made.add(dest)
    missing = [str(dest) for _, dest in pending if dest not in made]
    if missing:
        raise SystemExit("image composite failed:\n" + "\n".join(missing[:12]))
    if proc.stderr.strip():
        print(proc.stderr.strip()[:500])
    return sizes


def gallery(images, prefix, caption=None, priority=False) -> str:
    blocks = ['<div class="gallery">']
    for index, image in enumerate(images):
        loading = ""
        if index == 0 and priority:
            loading = ' fetchpriority="high"'
        elif index > 0:
            loading = ' loading="lazy"'
        alt = esc(image["alt"])
        src = esc(prefix + image["src"])
        block = (
            "<figure>"
            '<button class="shot" type="button">'
            f'<img src="{src}" width="{image["w"]}" height="{image["h"]}" alt="{alt}"{loading}>'
            "</button>"
        )
        if index == 0 and caption:
            block += f"<figcaption>{inline(caption, prefix)}</figcaption>"
        block += "</figure>"
        blocks.append(block)
    blocks.append("</div>")
    return "\n".join(blocks)


def specs_table(rows) -> str:
    body = ['<dl class="specs">']
    for label, value in rows:
        body.append(f"<div><dt>{esc(label)}</dt><dd>{inline(value, '')}</dd></div>")
    body.append("</dl>")
    return "\n".join(body)


def crumbs(items, prefix) -> str:
    bits = ['<nav class="crumbs" aria-label="Breadcrumb">']
    for index, (label, href) in enumerate(items):
        if index:
            bits.append("<span aria-hidden=\"true\">/</span>")
        if href:
            bits.append(f'<a href="{esc(prefix + href)}">{esc(label)}</a>')
        else:
            bits.append(f"<span>{esc(label)}</span>")
    bits.append("</nav>")
    return "".join(bits)


NAV = [
    ("knives", "Knives", "folding-knives/"),
    ("series", "Series", "series/"),
    ("about", "About", "about/"),
    ("news", "News", "news/"),
    ("support", "Support", "support/"),
]

FOOTER = [
    (
        "The bench",
        [
            ("How to order", "how-to-order/"),
            ("Build assistant", "build-assistant/"),
            ("Half baked builds", "half-baked/"),
            ("Warranty and spa", "warranty/"),
            ("Trade-in", "trade-in/"),
            ("Upgrades", "upgrade/"),
            ("Service", "service/"),
        ],
    ),
    (
        "Company",
        [
            ("About", "about/"),
            ("News", "news/"),
            ("Reviews", "reviews/"),
            ("Dealers", "dealers/"),
            ("Become a dealer", "become-a-dealer/"),
            ("Trade shows", "trade-shows/"),
            ("Contact", "contact/"),
        ],
    ),
    (
        "More",
        [
            ("Hand carved series", "hand-carved/"),
            ("Halloween", "halloween/"),
            ("Support", "support/"),
            ("Fine print", "fine-print/"),
        ],
    ),
]


def shell(title, description, prefix, current, body) -> str:
    nav_links = []
    dialog_links = []
    for key, label, href in NAV:
        current_attr = ' aria-current="page"' if key == current else ""
        nav_links.append(f'<a href="{esc(prefix + href)}"{current_attr}>{esc(label)}</a>')
        dialog_links.append(f'<a href="{esc(prefix + href)}"{current_attr}>{esc(label)}</a>')
    nav_links.append(f'<a class="btn" href="{esc(prefix)}contact/">Contact</a>')
    dialog_links.append(f'<a href="{esc(prefix)}contact/">Contact</a>')

    footer_cols = []
    for heading, links in FOOTER:
        items = "\n".join(
            f'<li><a href="{esc(prefix + href)}">{esc(label)}</a></li>' for label, href in links
        )
        footer_cols.append(f"<div><h2>{esc(heading)}</h2><ul>{items}</ul></div>")

    year = "2026"
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__TITLE__</title>
  <meta name="description" content="__DESC__">
  <meta name="theme-color" content="#f3eee6">
  <link rel="icon" href="__PREFIX__favicon.svg" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&amp;family=Outfit:wght@400;500;600&amp;display=swap">
  <link rel="stylesheet" href="__PREFIX__css/site.css">
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-bar">
      <a class="brand" href="__PREFIX__">
        <span class="mark" aria-hidden="true">∞</span>
        <span class="brand-name"><strong>OLAMIC</strong><span>Cutlery</span></span>
      </a>
      <nav class="nav-inline" aria-label="Primary">
        __NAV__
      </nav>
      <button class="nav-toggle" type="button" data-open-nav>Menu</button>
    </div>
  </header>
  <main id="main">
    __BODY__
  </main>
  <footer class="site-footer">
    <div class="wrap footer-grid">
      <div>
        <p class="mark" aria-hidden="true">∞</p>
        <p>Olamic Cutlery, Inc.<br>650 S Bridge St, Suite A<br>Visalia, CA 93277</p>
        <p><a href="mailto:team@olamiccutlery.com">team@olamiccutlery.com</a><br>
        <a href="mailto:support@olamiccutlery.com">support@olamiccutlery.com</a></p>
      </div>
      __FOOTER__
    </div>
    <div class="wrap footer-note">
      <p>Never the same. Serialized knives, lifetime warranty, spa service.</p>
      <p>Preview site, __YEAR__. Forms stay in the browser and do not place an order.</p>
    </div>
  </footer>
  <dialog id="nav-dialog" aria-label="Menu">
    <nav class="dialog-nav">
      <button class="close-nav" type="button">Close</button>
      __DIALOG__
    </nav>
  </dialog>
  <dialog id="lightbox" aria-label="Photograph">
    <div class="lightbox-bar">
      <button type="button" data-prev>Previous</button>
      <button type="button" data-next>Next</button>
      <button type="button" data-close>Close</button>
    </div>
    <figure>
      <img alt="" width="1200" height="800">
      <figcaption></figcaption>
    </figure>
  </dialog>
  <script src="__PREFIX__js/site.js" defer></script>
</body>
</html>
"""
    return (
        html.replace("__TITLE__", esc(title))
        .replace("__DESC__", esc(description))
        .replace("__PREFIX__", prefix)
        .replace("__NAV__", "".join(nav_links))
        .replace("__FOOTER__", "".join(footer_cols))
        .replace("__YEAR__", year)
        .replace("__DIALOG__", "".join(dialog_links))
        .replace("__BODY__", body)
    )


def write_page(rel: str, title: str, description: str, current: str, body: str) -> None:
    prefix = "../" * rel.count("/")
    full_title = title if title.startswith("Olamic") else f"{title} · Olamic Cutlery"
    path = SITE / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(shell(full_title, description, prefix, current, body))


def form_fields(extra: str = "", message: bool = True) -> str:
    message_html = (
        '<label>Message<textarea name="message" required></textarea></label>' if message else ""
    )
    return f"""
    <div class="honeypot">
      <label>Leave this field empty if you're human<input type="text" name="company" tabindex="-1" autocomplete="off"></label>
    </div>
    <label>Name<input name="name" autocomplete="name" required></label>
    <label>Email<input name="email" type="email" autocomplete="email" required></label>
    {extra}
    {message_html}
    <button class="btn" type="submit">Send note</button>
    <p class="form-status" role="status"></p>
    """


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def folder(*parts) -> Path:
    return Path(ROOT, *parts)


MODELS = [
    {
        "slug": "appetizer",
        "name": "Appetizer",
        "tags": "slipjoint small",
        "kicker": "Non-locking · sub-2 in blade",
        "summary": "Andrey Kolesnikov's small folder, with a modular spine and a detent that holds it open and closed.",
        "lede": "A fidget-friendly non-locking folder, just shy of 4.5 inches overall, with a blade under 2 inches.",
        "story": [
            "The Appetizer is the newest small model in this archive, and the latest design here from Andrey Kolesnikov. It is a non-locking folder. One detent, on an integral tension bar on the clip side, holds the blade open and holds it closed.",
            "The spine is a swappable piece. The choices on the model page are a lanyard loop, a bottle opener, a carabiner, and a plain flush back that can take the usual backspacer work. The show side can leave titanium for Timascus or zirconium.",
            "Direct orders opened on the old site on February 14, 2022. A plain titanium show side started at $295, and the price moved with finish and material. The shop quoted a completion date after the build was confirmed, often a few working days out.",
            "Olamic showed the first one on Instagram on August 25, 2021, and asked people which backspacer they wanted. The answers were for the shop, not a poll that shipped.",
        ],
        "specs": [
            ("Blade", "Under 2 in"),
            ("Overall", "Just under 4.5 in"),
            ("Lock", "None. Detent on an integral tension bar"),
            ("Spine", "Plain, bottle opener, lanyard loop, or carabiner"),
            ("Show side", "Titanium, with Timascus and zirconium options"),
            ("Opening price", "$295 for a plain titanium show side, 2022"),
            ("Designer", "Andrey Kolesnikov"),
        ],
        "features": [
            "Modular backspacer",
            "Same finish list as the larger folders",
            "Serialized, like the rest of the line",
        ],
        "sources": [IMG / "appetizer"],
        "hero": "IMG_0377.png",
        "caption": "Appetizer from the shop photo set. The spine piece changes the back of the handle.",
        "related": ["busker", "whippersnapper", "aura"],
    },
    {
        "slug": "busker",
        "name": "Busker",
        "tags": "front frame small",
        "kicker": "Front flipper · frame lock",
        "summary": "The small one. A 2.375 inch M390 blade, opened a lot of ways, and not a shrunk 247.",
        "lede": "Olamic's first folder with a blade under 3 inches. Shown at Blade Show 2017.",
        "story": [
            "The Busker is the small one. The model page lists a 2.375 inch blade, 0.138 inch stock, 6 inches overall, 3.5 inches closed, and 2.99 ounces with a backbar or 2.75 ounces on standoffs. Later Table notes and reviews often round the blade to 2.5 inches and the weight to about 2.95 ounces.",
            "It is a titanium frame lock on a caged bearing and a ceramic detent. A front flipper is the main open, plus an oval thumb hole. The old page said the knife can be opened at least ten ways. Named shapes are Largo, Semper, and Gusto, and the earlier Vampo. Steel on the page is Bohler M390. MagnaCut and carbon-fiber featherweight builds, down around 2.12 ounces, showed up later.",
            "The handle is curved and chamfered so the edge sits below the knuckles. It cuts like a small utility knife. It is not a miniature Wayfarer.",
            "A plain version started at $365 on that page. Archive pieces run from stonewashed mid-techs into carved one-offs. Everyday Commentary scored a Busker 18 out of 20 in 2017 and called it custom quality at a production pace.",
        ],
        "specs": [
            ("Blade", "2.375 in, 0.138 in thick"),
            ("Overall", "6.0 in"),
            ("Closed", "3.5 in"),
            ("Weight", "2.99 oz with backbar, 2.75 oz on standoffs"),
            ("Handle thickness", "0.42 in"),
            ("Steel", "Bohler M390. MagnaCut on later light builds"),
            ("Lock", "Titanium frame lock, stainless lockbar insert"),
            ("Open", "Front flipper and oval thumb hole"),
            ("Shapes", "Largo, Semper, Gusto, Vampo"),
            ("Hardware", "6AL-4V titanium, ceramic detent, ceramic clip ball"),
        ],
        "features": [
            "Caged bearings",
            "Floating backbar or standoffs",
            "Ceramic detent ball",
        ],
        "sources": [IMG / "busker"],
        "hero": "IMG_2296.png",
        "caption": "Busker with a carved handle. Blade shapes on this model are Largo, Semper, Gusto, and Vampo.",
        "related": ["whippersnapper", "wayfarer-247", "appetizer"],
        "quote": (
            "Custom quality, production availability and design creativity. We have a winner.",
            "Everyday Commentary, December 2017. The written score was 18 out of 20.",
            "https://www.everydaycommentary.com/www.everydaycommentary.com/2017/12/18/olamic-busker-review",
        ),
    },
    {
        "slug": "whippersnapper",
        "name": "Whippersnapper",
        "tags": "front frame small",
        "kicker": "Front flipper · frame lock",
        "summary": "Kolesnikov's next small folder after the Busker. A four-finger grip, a choil, and CPM 20CV.",
        "lede": "Debuted at Blade Show 2019. The frame-lock run is the first version. The bolster lock followed.",
        "story": [
            "Andrey Kolesnikov designed the Whippersnapper as the step after the Busker. Olamic launched it on November 11, 2019, with American CPM 20CV and the same frame-lock pattern as the other mid-techs.",
            "The blade is about 2.75 inches. Overall length is 6.875 inches. Closed length is about 4.25 inches with the flipper tab, and weight sits a little over 3 ounces, with shop and retailer notes clustering around 3.3 to 3.5. It is a front flipper with a blade hole, caged bearings, and dual stop pins.",
            "Next to the Busker you get a full four-finger grip, a larger flipper tab, and a finger choil. Shapes are wharncliffe, wharnfoot, and sheepsfoot. The profile is daily carry, not a tactical one.",
            "The old frame-lock page said that run had paused and the design was not going away. The next chapter is the [[bolster lock|models/whippersnapper-bolsterlock/]].",
        ],
        "specs": [
            ("Blade", "About 2.75 in"),
            ("Overall", "6.875 in"),
            ("Closed", "About 4.25 in with the flipper tab"),
            ("Weight", "A little over 3 oz"),
            ("Steel", "CPM 20CV. CTS-XHP and S90V on some later runs"),
            ("Lock", "Titanium frame lock on this version"),
            ("Open", "Front flipper and blade hole"),
            ("Shapes", "Wharncliffe, wharnfoot, sheepsfoot"),
            ("Designer", "Andrey Kolesnikov"),
        ],
        "features": [
            "Caged bearings and dual stop pins",
            "Long floating backspacer",
            "3D pocket clip, revised from the Busker",
        ],
        "sources": [IMG / "whippersnapper"],
        "hero": "IMG_1681.png",
        "caption": "Frame-lock Whippersnapper. The bolster-lock version keeps this size and adds scales.",
        "related": ["whippersnapper-bolsterlock", "busker", "wayfarer-247"],
    },
    {
        "slug": "whippersnapper-bolsterlock",
        "name": "Whippersnapper Bolsterlock",
        "tags": "front bolster small",
        "kicker": "Front flipper · bolster lock",
        "summary": "Same Whippersnapper, with an integral front bolster and scales. Micarta, carbon fiber, Damasteel.",
        "lede": "The second run. Size stays. The handle opens up to the materials Olamic had been using on liner locks since 2013.",
        "story": [
            "By mid-2021 the first Whippersnapper run, a full titanium frame lock in CPM 20CV, was finished. The bolster lock keeps the design and the dimensions and adds an integral front bolster plus scales.",
            "Olamic described it as a return to liner-lock habits. Different scale materials, and titanium that does not have to look like plain titanium. Steels on this run are CTS-XHP, CPM S90V, and Damasteel in the Super Dense Twist pattern.",
            "Ordering on the old page used Half Baked builds, where the scale was already chosen and the buyer finished the rest, and Quickforms for a faster timeless build. The three Quickforms were OD green canvas Micarta, burlap Micarta, and twill carbon fiber. Posted prices were $645 for the Micartas and $745 for carbon fiber.",
            "Maker's Choice was the other door. You handed the finish decisions back to the shop.",
        ],
        "specs": [
            ("Size", "Same as the frame-lock Whippersnapper"),
            ("Blade", "About 2.75 in"),
            ("Overall", "6.875 in"),
            ("Lock", "Bolster lock with scales"),
            ("Steel", "CTS-XHP, CPM S90V, or Damasteel Super Dense Twist"),
            ("Shapes", "Wharncliffe and sheepsfoot on the listed builds"),
            ("Quickforms", "Canvas Micarta, burlap Micarta, twill carbon fiber"),
            ("Turnaround", "A few working days once a Half Baked order was confirmed"),
        ],
        "features": [
            "Integral front bolster",
            "Scale materials going back to the 2013 liner locks",
            "Filework, clip material, and finish still chosen per knife",
        ],
        "sources": [MODELS_DIR / "2026_transparent" / "wsbl", MODELS_DIR / "2025_transparent" / "wsbl"],
        "hero": None,
        "caption": "Bolster-lock Whippersnapper. The show scale is the part that changes the knife.",
        "related": ["whippersnapper", "busker", "wayfarer-compact"],
    },
    {
        "slug": "gambit",
        "name": "Gambit",
        "tags": "liner custom",
        "kicker": "Liner lock · full custom",
        "summary": "A small collaboration with Serge Panchenko. Fifty-eight were made, each one different, and none of it on a CNC.",
        "lede": "The fourth custom folder out of the Visalia shop, from a Blade Show conversation in 2015.",
        "story": [
            "Early in 2015 the custom line needed a smaller knife. At Blade Show that year the Olamic table sat next to Serge Panchenko, whose California shop is a couple of hours from Visalia. The Gambit came out of that conversation.",
            "The page is honest about the blade. The shape line says they don't have a name for it. Steel is CPM S30V. Cutting edge is 2.875 inches, overall 7.25 inches, closed 4.25 inches, weight somewhere between 4.5 and 6.8 ounces depending on the build.",
            "Construction matches the other early customs. No CNC. Outlines are cut, then the knife is ground, milled, and contoured by hand in Visalia. To the date of that page, 58 had been made.",
            "The photo set in this folder does not include a separate Gambit gallery. The pictures on this page are other full-custom liner locks from the same shop, so you can see the construction. They are not claimed as Gambit serials.",
        ],
        "specs": [
            ("Cutting edge", "2.875 in / 73.0 mm"),
            ("Thickness", "0.146 in / 3.7 mm"),
            ("Overall", "7.25 in / 184 mm"),
            ("Closed", "4.25 in / 108 mm"),
            ("Handle thickness", "0.49 to 0.61 in"),
            ("Weight", "4.5 to 6.8 oz"),
            ("Steel", "CPM S30V"),
            ("Lock", "Titanium liner lock"),
            ("Made", "58 pieces at the time of the model page"),
            ("Designer", "Serge Panchenko, with Olamic"),
        ],
        "features": [
            "No CNC",
            "Hand-ground blade, contoured handle",
            "Jeweled liners, caged bearings, internal stop pin",
        ],
        "sources": [MODELS_DIR / "2024_transparent" / "linerlock"],
        "hero": None,
        "slice": (0, 8),
        "caption": "A Visalia liner lock from the archive. The Gambit is built this way. This frame is not labeled as one of the 58.",
        "related": ["wayfarer-compact", "wayfarer-classic", "busker"],
    },
    {
        "slug": "wayfarer-compact",
        "name": "Wayfarer Compact",
        "tags": "liner custom",
        "kicker": "Liner lock · full custom",
        "summary": "The smaller handmade Wayfarer. A 3.375 inch edge, no CNC, and the knife the 247 grew out of.",
        "lede": "Released September 2015, after people asked for a Wayfarer they could actually pocket.",
        "story": [
            "The Compact is the second folding model, a smaller Wayfarer Classic. The first ones were built in 2015. It is still a full custom liner lock. Nothing on it is CNC.",
            "Olamic kept the Wayfarer lessons and moved them into a more daily size. A cutout in the blade lets you open it without the flipper. The spec chart lists a 3.375 inch cutting edge, 0.146 inch stock, 8.125 inches overall, 4.75 inches closed, and a weight that moves between 6 and 8 ounces with the materials.",
            "Current steel on that chart is CTS-XHP, after CTS-204P. Liners, backspacer, and clip start in titanium. Scales, bolsters, inlays, filework, and anodizing are the rest of the conversation. The old page's material list runs through zirconium, several carbon fibers, G10, Micarta, kirinite, Raffir, camel bone, desert ironwood, mammoth tooth, koa, copper, bronze, brass, titanium damascus, mokume, and more.",
            "The Wayfarer 247 is the mid-tech that came from this knife. The Compact is still made one at a time when the books are open. Write the shop with a theme if you want one.",
        ],
        "specs": [
            ("Cutting edge", "3.375 in / 85.7 mm"),
            ("Thickness", "0.146 in / 3.7 mm"),
            ("Overall", "8.125 in / 206.4 mm"),
            ("Closed", "4.75 in"),
            ("Weight", "6 to 8 oz, depending on the build"),
            ("Handle thickness", "0.47 to 0.63 in"),
            ("Steel", "CTS-XHP. Earlier, CTS-204P"),
            ("Lock", "Titanium liner lock"),
            ("Open", "Flipper, or the blade cutout"),
            ("Shapes", "Drop point, with an optional compound grind"),
        ],
        "features": [
            "No CNC. Hand ground, hand contoured",
            "Caged bearings on a thrust washer",
            "Hand-sculpted 3D clip",
            "Jeweled liners and a ceramic detent",
        ],
        "sources": [MODELS_DIR / "2025_transparent" / "linerlock"],
        "hero": None,
        "caption": "Handmade liner lock from the Visalia bench. The Compact is built this way, one knife at a time.",
        "related": ["wayfarer-classic", "wayfarer-247", "gambit"],
    },
    {
        "slug": "wayfarer-247",
        "name": "Wayfarer 247",
        "tags": "frame",
        "kicker": "Frame lock · rear flipper",
        "summary": "The everyday knife, and the one the shop finishes a million ways. No two leave the bench alike.",
        "lede": "Released May 2016. A smaller, pocketable take on the custom Wayfarer built with Michael Vagnino.",
        "story": [
            "The 247 is the knife Olamic has kept working on since May 2016. The model page lists a 3.5 inch cutting edge, 0.138 inch stock, 8 inches overall, 4.82 inches closed, 0.51 inch handle, and 4.99 ounces. Reviews often print 8.125 inches overall and an even 5 ounces. Same knife, two rulers.",
            "Caged bearings, a floating backspacer, a ceramic detent, and a skeletonized rear flipper are the base. Later knives can take a thumbstud that adjusts, reverses, or comes off, or a flipper delete. The lockbar insert is hardened stainless, with an overtravel stop.",
            "The page's blade list, with the seasons they showed up: drop point from summer 2013's custom line, harpoon in summer 2017, sheepscliffe and tanto in spring 2018, then bowie, wharncliffe, tanto II, cutlass, purist, and mouflon in fall 2022. First-run steel was Bohler Elmax. The chart's current steel is Bohler M390. Table pieces have also been CPM S90V and CTS-XHP.",
            "Parts that have to be precise are pre-machined. Everything you notice is done in Visalia, because most of the finishes cannot be machined anyway. Hole patterns, carving, anodizing, inlays, Molten, Acid Rain, Kinetic, Entropic. The 247 is the canvas.",
            "In 2023 the 247CF put Fatcarbon on the show side for the first time, with S90V and a live mockup when you ordered. Everyday Commentary scored an early 247 19 out of 20. BladeReviews called it the titanium flipper you buy when you want the knife made your way.",
        ],
        "specs": [
            ("Cutting edge", "3.5 in / 88.9 mm"),
            ("Thickness", "0.138 in / 3.5 mm"),
            ("Overall", "8.0 in / 203.2 mm"),
            ("Closed", "4.82 in / 122.4 mm"),
            ("Weight", "4.99 oz / 141 g"),
            ("Handle thickness", "0.51 in / 13.0 mm"),
            ("Steel", "Bohler M390 on the model chart. Elmax on the first run. S90V and CTS-XHP on later pieces"),
            ("Lock", "Titanium frame lock"),
            ("Open", "Rear flipper. Thumbstud or flipper delete on later knives"),
            ("Shapes", "Drop point, harpoon, sheepscliffe, tanto, cutlass, purist, wharncliffe, mouflon, bowie"),
        ],
        "features": [
            "Caged bearings on a thrust washer",
            "Floating backspacer and integral lanyard hole",
            "All titanium hardware",
            "Chamfered blade cutout",
        ],
        "sources": [IMG / "wayfarer 247"],
        "hero": "IMG_1920.png",
        "caption": "Wayfarer 247. Finishes on this model change from serial to serial.",
        "related": ["wayfarer-compact", "swish", "aura", "busker"],
        "quote": (
            "If you want a titanium flipper framelock with uncompromising quality and the ability to make it your own, then the 247 is an excellent choice.",
            "BladeReviews, December 2018.",
            "https://bladereviews.com/olamic-wayfarer-247-review/",
        ),
    },
    {
        "slug": "aura",
        "name": "Aura",
        "tags": "auto",
        "kicker": "Button lock · out-the-side automatic",
        "summary": "The first Olamic automatic. A 247-sized titanium knife that opens itself.",
        "lede": "Single-action button lock, 3.5 inches of CPM 20CV, all titanium. Books opened April 1, 2025.",
        "story": [
            "Aura is the first automatic. The old auto page lists a 3.5 inch CPM 20CV blade at 0.158 inch, 8.5 inches overall, 5 inches closed, 4.4 ounces, and a 0.576 inch handle. It is a button lock, single action, out the side. Right hand, tip up.",
            "The blade is a clip or a drop point depending on the piece. A nugget-sculpted backspacer shows up often. Finishes are the same list as the manuals. Frosty, Antique Entropic, Rainforest, anodizing, the rest of the Never the Same work.",
            "A custom-order note in the Table archive put a starting build at $795, including a handle finish and a nugget or fileworked backspacer, with a short turnaround. Timascus or zirconium clips were the usual upgrade.",
            "The April 1, 2025 announcement opened the books on the all-titanium auto. This preview does not take the order. Use the contact page or team@olamiccutlery.com and ask what the current book looks like.",
        ],
        "specs": [
            ("Blade", "3.5 in, 0.158 in thick"),
            ("Overall", "8.5 in"),
            ("Closed", "5.0 in"),
            ("Weight", "4.4 oz"),
            ("Handle thickness", "0.576 in"),
            ("Steel", "CPM 20CV"),
            ("Lock", "Button lock, single-action automatic"),
            ("Handle", "All titanium"),
            ("Clip", "Right hand, tip up"),
            ("Shapes", "Clip point or drop point"),
        ],
        "features": [
            "Out-the-side automatic",
            "Nugget backspacer as a common option",
            "Same finish vocabulary as the 247",
        ],
        "sources": [IMG / "aura"],
        "hero": "IMG_1099.png",
        "caption": "Aura, the button-lock automatic. This one wears a sculpted, heat-colored handle.",
        "related": ["wayfarer-247", "swish", "busker"],
    },
    {
        "slug": "swish",
        "name": "Swish",
        "tags": "frame",
        "kicker": "Frame lock · rear flipper",
        "summary": "Named for the upswept slicer. Elmax, a long fuller, and a quiet bearing flipper.",
        "lede": "Released April 2017. It sits between the 247 and the longer Rainmaker.",
        "story": [
            "The Swish is named for the blade. Knife Informer called the profile a modified spear that curves like a swish. The model page lists a 3.8 inch blade, 8.25 inches overall, 4.875 inches closed, titanium handle and backspacer, and Bohler Elmax. Shop notes put the weight at 4.35 ounces. Knife Informer's sample weighed 4.6.",
            "It is a frame-lock flipper on bearings, often with a long fuller and a thin full-flat grind. Some listings print a 0.12 inch slicer grind. The clip is short and uses a large ball bearing. Action on the reviews is quiet.",
            "Damasteel blades and matching clips were offered on the Swish, the 247, and the Busker, hardened to 60 HRC in the Super Dense Twist pattern, 100 pieces per model.",
            "Knife Informer scored the Swish 80 percent in a mid-tech review and called the fit the part machining does not do. Their complaints were the clip and lockbar access, not the grind.",
        ],
        "specs": [
            ("Blade", "3.8 in / 96.5 mm"),
            ("Overall", "8.25 in / 209.6 mm"),
            ("Closed", "4.875 in / 123.8 mm"),
            ("Weight", "About 4.35 oz on shop notes"),
            ("Steel", "Bohler Elmax. Damasteel on a limited run"),
            ("Handle", "6AL-4V titanium frame, backspacer, and clip"),
            ("Lock", "Frame lock"),
            ("Open", "Rear flipper on bearings"),
            ("Released", "April 2017"),
        ],
        "features": [
            "Upswept slicer grind",
            "Often a long fuller",
            "Short clip with a ball bearing",
        ],
        "sources": [IMG / "swish"],
        "hero": "IMG_1461.png",
        "caption": "Swish. The blade is the upswept slicer the model is named for.",
        "related": ["wayfarer-247", "rainmaker", "soloist"],
        "quote": (
            "A superb effort from the team at Olamic and well worthy of your hard earned dollar. A mid-tech marvel in both looks and performance.",
            "Knife Informer. Quality and performance 83, value 77, overall 80.",
            "https://knifeinformer.com/olamic-swish-review/",
        ),
    },
    {
        "slug": "rainmaker",
        "name": "Rainmaker",
        "tags": "frame",
        "kicker": "Frame lock · rear flipper",
        "summary": "A slim handle hiding a 4 inch blade. The frame-lock version of Alexander Birykov's custom.",
        "lede": "The mid-tech follow-up. Drop point or harpoon, flat or hollow, M390, all titanium.",
        "story": [
            "The frame-lock Rainmaker is the semi-custom version of the handmade Rainmaker. Flipper, all titanium, two blade shapes, each in flat and hollow grinds. The page lists a 4.0 inch blade, 0.137 inch stock, 9.75 inches overall, 0.48 inch handle, and 5.53 ounces. A 2019 note put closed length at 5.5 inches.",
            "Steel is Bohler M390. Shapes are drop point and harpoon. The June 2019 blade list split each shape into a flat grind and a hollow grind, with mirror reserved for the hollows.",
            "The idea, from the custom, is a straight knife with some character. Long blade, thin pocket. Serial numbers on the classics live inside the backspacer. Frame-lock serials use a suffix for the shape. D for drop, H for harpoon.",
            "Anything offered on the other frame locks can be asked for here. The old build form has been closed and opened with the books. Ask before you assume a slot.",
        ],
        "specs": [
            ("Blade", "4.0 in, 0.137 in thick"),
            ("Overall", "9.75 in"),
            ("Closed", "5.5 in, from the 2019 spec note"),
            ("Weight", "5.53 oz"),
            ("Handle thickness", "0.48 in"),
            ("Steel", "Bohler M390"),
            ("Shapes", "Drop point and harpoon, flat or hollow"),
            ("Lock", "Titanium frame lock"),
            ("Open", "Rear flipper, caged bearings"),
            ("Handle", "6AL-4V frames, backbar, clip, and hardware"),
        ],
        "features": [
            "Long blade in a thin handle",
            "Floating backbar",
            "Same finish list as the 247 and the Swish",
        ],
        "sources": [
            MODELS_DIR / "2025_transparent" / "rainmaker",
            MODELS_DIR / "2026_transparent" / "rainmaker",
        ],
        "hero": None,
        "caption": "Rainmaker. Four inches of blade, carried in a slim titanium handle.",
        "related": ["rainmaker-classic", "swish", "soloist"],
    },
    {
        "slug": "rainmaker-classic",
        "name": "Rainmaker Classic",
        "tags": "liner custom",
        "kicker": "Liner lock · full custom",
        "summary": "The second folder out of Visalia. May 2015, about a hundred in the first run, no CNC.",
        "lede": "Alexander Birykov's slim 4 inch custom. First-run steel was nitrogen Z-Finit.",
        "story": [
            "The Rainmaker was the second folding model from the California shop, released May 2015. The first run was about 100 pieces. Alexander Birykov wanted a straight knife with character. A slim handle, a long blade, and a serial number on the inside of the backspacer.",
            "The classic chart lists a 4.0 to 4.125 inch cutting edge depending on the choil, 0.146 inch stock, 9.75 inches overall, 5.5 inches closed, handle thickness 0.55 to 0.65 inch, and weight from 5.5 to 7.5 ounces. Shapes are drop point, harpoon, and harpoon with a compound grind.",
            "First-run steel was Z-Finit, a nitrogen steel. Later classics moved through CTS-XHP to CTS-204P. The liners stay titanium. Natural scale materials suit the thin handle, because a lot of them only come in small pieces.",
            "No CNC. The slim liner lock on this page is the construction. Carved classics, including thematic pieces, have sold much higher than the frame-lock run. The Sailor and Lafayette Escadrille carvings were in the three-thousand range.",
        ],
        "specs": [
            ("Cutting edge", "4.0 to 4.125 in, depending on the choil"),
            ("Thickness", "0.146 in / 3.7 mm"),
            ("Overall", "9.75 in / 248 mm"),
            ("Closed", "5.5 in / 140 mm"),
            ("Handle thickness", "0.55 to 0.65 in"),
            ("Weight", "5.5 to 7.5 oz"),
            ("Steel", "CTS-204P on the chart. Z-Finit first run. CTS-XHP in between"),
            ("Shapes", "Drop point, harpoon, harpoon with compound grind"),
            ("Lock", "Titanium liner lock"),
            ("First run", "About 100 pieces, May 2015"),
        ],
        "features": [
            "No CNC",
            "Serial inside the backspacer",
            "Hand-sculpted 3D clip",
            "Jeweled liners",
        ],
        "sources": [MODELS_DIR / "2026_transparent" / "linerlock"],
        "hero": None,
        "caption": "Liner-lock construction from Visalia. The Rainmaker Classic is ground and fitted this way.",
        "related": ["rainmaker", "wayfarer-classic", "soloist"],
    },
    {
        "slug": "wayfarer-classic",
        "name": "Wayfarer Classic",
        "tags": "liner custom",
        "kicker": "Liner lock · full custom",
        "summary": "The first Visalia folder. Blade Show 2013, twelve knives on the table, still built without a CNC.",
        "lede": "Michael Vagnino's large Wayfarer. A 3.875 inch edge and a handle that is always contoured by hand.",
        "story": [
            "The Wayfarer, now the Wayfarer Classic, is the first folder built at the Visalia shop. It was released at Blade Show 2013. Twelve sold at the show. Michael Vagnino designed it, and the size is the point. People who wanted a hefty knife kept asking for it.",
            "The chart lists a 3.875 inch cutting edge, 0.146 inch stock, 9.25 inches overall, 5.25 inches closed, and 6 to 8 ounces. Handle thickness runs 0.53 to 0.63 inch. Shapes are the classic drop point, harpoon, sheepscliffe, and tanto. Drop point and harpoon can take a compound grind.",
            "Steel on the chart is CTS-204P, described on the page as an American-made equivalent to M390. The first run was S35VN. CPM 3V, CPM 154, CTS-B75P, and CTS-XHP have also been used.",
            "There is no CNC in the process. Outlines are cut, then the blade is ground by hand and the handle is contoured. The page's claim is tens of millions of builds. Liners are titanium. Everything else is a conversation.",
        ],
        "specs": [
            ("Cutting edge", "3.875 in / 98.4 mm"),
            ("Thickness", "0.146 in / 3.7 mm"),
            ("Overall", "9.25 in / 235 mm"),
            ("Closed", "5.25 in / 133.4 mm"),
            ("Weight", "6 to 8 oz"),
            ("Handle thickness", "0.53 to 0.63 in"),
            ("Steel", "CTS-204P. First run S35VN"),
            ("Shapes", "Drop point, harpoon, sheepscliffe, tanto"),
            ("Lock", "Titanium liner lock"),
            ("Designer", "Michael Vagnino"),
        ],
        "features": [
            "No CNC",
            "Hand-ground blade",
            "Hand-sculpted 3D clip and jeweled liners",
            "Protected lanyard hole and a skeletonized flipper",
        ],
        "sources": [MODELS_DIR / "2024_transparent" / "linerlock"],
        "hero": None,
        "slice": (8, 8),
        "caption": "Handmade liner lock. The Wayfarer Classic is the large one, built one at a time since Blade Show 2013.",
        "related": ["wayfarer-compact", "wayfarer-247", "rainmaker-classic"],
    },
    {
        "slug": "soloist",
        "name": "Soloist",
        "tags": "frame",
        "kicker": "Frame lock · flipper or thumbstud",
        "summary": "The large tactical folder. Thick M390, two shapes, a grip that locks in forward or reverse.",
        "lede": "Scout is the safer sheepsfoot. Agent is the pointed drop point. Both are built like a tool, not a gent's knife.",
        "story": [
            "The Soloist is the heavy end of the lineup. The model page lists a 4.0 inch blade in 0.155 inch M390, 10.25 inches overall, a 0.49 inch handle, and 6.5 ounces. Table listings often print a 4.125 inch blade, a 4 inch cutting edge, 9.75 inches overall, 5.5 inches closed, and about 6.4 ounces. Retailer sheets wander inside that band. It is one design.",
            "Two shapes. Scout is a sheepsfoot with a blunter tip. Agent is the pointy drop point. Serial suffixes follow the blade. S and A.",
            "You open it with the flipper or with Olamic's thumbstud. The stud can be adjusted, reversed, removed, rotated, or doubled, in a checkered oblique or a domed head. The handle is a pistol grip meant to lock the hand in both directions. Long floating backspacer, oversized standoffs, rotation-free pivots, titanium hardware.",
            "This is not the pocket partner to the Busker. If the 247 is the everyday canvas, the Soloist is the one you notice on a belt.",
        ],
        "specs": [
            ("Blade", "4.0 in on the model page, 0.155 in thick"),
            ("Overall", "10.25 in on the model page"),
            ("Weight", "6.5 oz on the model page"),
            ("Handle thickness", "0.49 in"),
            ("Steel", "Bohler M390"),
            ("Shapes", "Scout sheepsfoot, Agent drop point"),
            ("Lock", "Titanium frame lock"),
            ("Open", "Flipper or adjustable thumbstud"),
            ("Handle", "6AL-4V frames, backbar, clip, and hardware"),
        ],
        "features": [
            "Thumbstud can be doubled, reversed, or removed",
            "Long floating backspacer and oversized standoffs",
            "Rotation-free pivots",
            "Pistol grip for forward and reverse",
        ],
        "sources": [IMG / "soloist", MODELS_DIR / "2025_transparent" / "soloist"],
        "hero": "IMG_0872.png",
        "caption": "Soloist. Scout blunts the tip. Agent keeps it.",
        "related": ["rainmaker", "wayfarer-247", "swish"],
    },
    {
        "slug": "silhouette",
        "name": "Silhouette",
        "tags": "kitchen",
        "kicker": "Chef's knife · CPM MagnaCut",
        "summary": "The first proper Olamic chef's knife. A 7.5 inch satin MagnaCut blade and a carbon-fiber handle.",
        "lede": "Released February 6, 2024. Serialized, sheathed, and ground as a traditional chef's profile.",
        "story": [
            "The Silhouette is a chef's knife, not a folder. Olamic released it on February 6, 2024, and called it the first proper one. The blade is a 7.5 inch traditional profile in CPM MagnaCut, hardened to 63.5 to 64 HRC, with a fine satin finish.",
            "The first batch used a maker-exclusive carbon fiber handle on polished stainless Corby bolts. Overall length is 12 inches. The blade is 0.12 inch thick and 1.625 inch tall. Weight is 5.9 ounces, or 8.1 ounces in the leather sheath.",
            "The page lists a full-length top swedge, a crowned tang, and hand-contoured scales. Each knife is serialized.",
            "Fixed blades have been part of Olamic since 2010, forged in Russia in the shop's own high-carbon vanadium damascus. The Silhouette is the kitchen knife in that longer story, made as a numbered run rather than a one-off hunter.",
        ],
        "specs": [
            ("Blade", "7.5 in / 190.5 mm"),
            ("Overall", "12.0 in / 304.8 mm"),
            ("Thickness", "0.12 in / 3.0 mm"),
            ("Height", "1.625 in / 41.3 mm"),
            ("Weight", "5.9 oz, 8.1 oz with the sheath"),
            ("Steel", "CPM MagnaCut, 63.5 to 64 HRC"),
            ("Finish", "Fine satin"),
            ("Handle", "Maker-exclusive carbon fiber, stainless Corby bolts"),
            ("Other", "Top swedge, crowned tang, hand-contoured scales, leather sheath"),
        ],
        "features": [
            "Serialized",
            "Leather sheath",
            "Traditional chef's profile",
        ],
        "sources": [IMG / "silhouette", MODELS_DIR / "2025_transparent" / "silhouette"],
        "hero": "IMG_9702.png",
        "caption": "Silhouette chef's knife. MagnaCut, satin, carbon fiber, Corby bolts.",
        "related": ["wayfarer-247", "appetizer"],
    },
]


BLADE_IN = {
    "appetizer": 1.9,
    "busker": 2.375,
    "whippersnapper": 2.75,
    "whippersnapper-bolsterlock": 2.75,
    "gambit": 2.875,
    "wayfarer-compact": 3.375,
    "wayfarer-247": 3.5,
    "aura": 3.5,
    "wayfarer-classic": 3.875,
    "swish": 3.8,
    "rainmaker": 4.0,
    "rainmaker-classic": 4.06,
    "soloist": 4.0,
    "silhouette": 7.5,
}

ASSIST = {
    "appetizer": (["Standard"], ["Shop steel"], "Non-locking", "Detent"),
    "busker": (["Largo", "Semper", "Gusto", "Vampo"], ["M390", "MagnaCut"], "Frame lock", "Front flipper"),
    "whippersnapper": (["Wharncliffe", "Wharnfoot", "Sheepsfoot"], ["20CV", "CTS-XHP", "S90V"], "Frame lock", "Front flipper"),
    "whippersnapper-bolsterlock": (["Wharncliffe", "Sheepsfoot"], ["CTS-XHP", "S90V", "Damasteel"], "Bolster lock", "Front flipper"),
    "gambit": (["Gambit profile"], ["S30V"], "Liner lock", "Flipper"),
    "wayfarer-compact": (["Drop point", "Compound grind"], ["CTS-XHP"], "Liner lock", "Flipper or cutout"),
    "wayfarer-247": (
        ["Drop point", "Harpoon", "Sheepscliffe", "Tanto", "Cutlass", "Purist", "Wharncliffe", "Mouflon", "Bowie"],
        ["M390", "S90V", "CTS-XHP", "Elmax", "Damasteel"],
        "Frame lock",
        "Rear flipper",
    ),
    "aura": (["Clip point", "Drop point"], ["20CV"], "Button lock", "Automatic"),
    "swish": (["Swish slicer"], ["Elmax", "Damasteel"], "Frame lock", "Rear flipper"),
    "rainmaker": (["Drop point", "Harpoon"], ["M390"], "Frame lock", "Rear flipper"),
    "rainmaker-classic": (["Drop point", "Harpoon", "Compound harpoon"], ["CTS-204P", "CTS-XHP"], "Liner lock", "Flipper"),
    "wayfarer-classic": (
        ["Drop point", "Harpoon", "Sheepscliffe", "Tanto"],
        ["CTS-204P", "S35VN", "CTS-XHP"],
        "Liner lock",
        "Flipper",
    ),
    "soloist": (["Scout", "Agent"], ["M390"], "Frame lock", "Flipper or thumbstud"),
    "silhouette": (["Chef"], ["MagnaCut"], "Fixed blade", "Kitchen"),
}

FINISHES = [
    "Stonewash",
    "Satin",
    "Matte",
    "Two-tone",
    "PVD stonewash",
    "Acid Rain",
    "Kinetic Rain",
    "Kinetic Rainforest",
    "Kinetic Earth",
    "Molten",
    "Frosty",
    "Antique Entropic",
    "Orange peel",
    "Seabed",
    "Jeweled",
]


def series_entry(slug, title, model, offset, status, body, pieces):
    return {
        "slug": slug,
        "title": title,
        "model": model,
        "offset": offset,
        "status": status,
        "body": body,
        "pieces": pieces,
    }


SERIES = [
    series_entry("jazzy-buskers", "Jazzy Buskers", "busker", 1, "Limit 9. Old page: open, about two thirds carved.", [
        "Shallow carving on Buskers only. Instruments and players, color from anodizing, across the Busker blade shapes. Backbars, clips, and hardware change with the scheme.",
        "Sold on the old page: saxophone, trumpet, guitar, clarinet, jazz player, clarinet player. Still listed as open: drums, flute, upright bass.",
    ], ["Saxophone, sold", "Trumpet, sold", "Guitar, sold", "Clarinet, sold", "Jazz player, sold", "Clarinet player, sold", "Drums, listed open", "Flute, listed open", "Upright bass, listed open"]),
    series_entry("punkd-rainmakers", "Punk'd Rainmakers", "rainmaker", 0, "Limit 3. Old page: open, one of three done.", [
        "Three Rainmakers in bronze: Diesel, Steam, and Electro. A small series used to try finishes on bronze.",
        "Steampunk was sold. Dieselpunk and Electropunk were still open on the old page.",
    ], ["Steampunk, sold", "Dieselpunk, listed open", "Electropunk, listed open"]),
    series_entry("americana", "Americana", "wayfarer-classic", 0, "Limit 8. Old page: open, about three quarters done.", [
        "United States history, started in bronze on the liner locks. The old page left the reading of the portraits to you. The Chief and Chief Jr. might be the same man, decades apart.",
        "Sold names on that page include The Trapper, The Chief, Chief Jr., and The Mobster. A few spots were still open, and the shop was asking for ideas.",
    ], ["The Trapper, sold", "The Chief, sold", "Chief Jr., sold", "The Mobster, sold"]),
    series_entry("dragon-inlays", "Dragon Inlays", "wayfarer-247", 2, "Limit 6. Old page: open, half done, planned for 2019.", [
        "Bronze dragon inlays on the Wayfarer 247, so a carved depth sits in a titanium finish. Six dragons, different blade shapes and finishes. Numbers 1 through 3 were sold. The rest were open spots.",
    ], ["No. 1, sold", "No. 2, sold", "No. 3, sold", "Three spots listed open"]),
    series_entry("day-of-the-dead", "Day of the Dead", "busker", 3, "Limit 3. Closed.", [
        "Shallow carving, color from anodizing, on the Busker. Olamic is in California, and the series is that local calendar done in titanium. Three knives. All three were marked sold.",
    ], ["No. 1, sold", "No. 2, sold", "No. 3, sold"]),
    series_entry("ancient-civilizations", "Ancient Civilizations", "wayfarer-247", 4, "Limit 12. Old page: open, about three quarters done.", [
        "Themes, images, and cultures from a few thousand years back, carved in bronze and titanium, on the frame locks.",
        "Sold on the old page: Egyptian, Rosetta Stone, Nisroch, Olmec, Anubis, and Shu.",
    ], ["Egyptian, sold", "Rosetta Stone, sold", "Nisroch, sold", "Olmec, sold", "Anubis, sold", "Shu, sold"]),
    series_entry("sundry-solitary", "Sundry & Solitary", "swish", 1, "No limit. One-offs that do not belong to a set.", [
        "Knives built for a person, a gift, a test, or a joke, and not repeated. The old page showed Eyepatch Time, Seven Skull Swish, Tiger on Bronze, Gambling Jester, Fleur-de-lys, Three 7 Ace, and a Split Personality set.",
    ], ["Eyepatch Time, sold", "Seven Skull Swish, sold", "Tiger on Bronze, sold", "Gambling Jester, sold", "Fleur-de-lys", "Three 7 Ace, sold", "Split Personality set, sold"]),
    series_entry("thematic-skulls", "Thematic Skulls", "wayfarer-247", 5, "Limit 15. Old page: open, most of them sold.", [
        "Skulls that do not share a motif. Each one has its own. The old page's sold list includes Techno Is Dead, Jester's Last Trick, Under Pressure, Nailed It, Knot Your Day, and 247 Edition 247.",
    ], ["Techno Is Dead, sold", "Jester's Last Trick, sold", "Under Pressure, sold", "Nailed It, sold", "Knot Your Day, sold", "247 Edition 247, sold"]),
    series_entry("vampy-buskers", "Vampy Buskers", "busker", 4, "Limit 4. Closed.", [
        "Four Buskers, four vampires, each with a distinct fang. Orpheus, Zagan, Azazel, and Armand. All sold.",
    ], ["Orpheus, sold", "Zagan, sold", "Azazel, sold", "Armand, sold"]),
    series_entry("world-history-greats", "World History Greats", "wayfarer-classic", 2, "Limit 10. Old page: open, about 60 percent done.", [
        "People who stayed in the record, carved in bronze. Sold on the old page: King Sargon, Genghis Khan, Sun Tzu, King Solomon, Leonardo da Vinci, and Julius Caesar.",
    ], ["King Sargon, sold", "Genghis Khan, sold", "Sun Tzu, sold", "King Solomon, sold", "Leonardo da Vinci, sold", "Julius Caesar, sold"]),
    series_entry("heroes-villains", "Heroes & Villains", "busker", 5, "Limit 10. Old page: open, about 80 percent done.", [
        "Comic color, laid on with 2400 Series GunKote over carving, on the 247, the Busker, and the Swish. Sold names include the Joker, Batman, and Captain America.",
    ], ["Joker, sold", "Batman, sold", "Captain America, sold"]),
    series_entry("halloween", "Halloween", "busker", 0, "A short run each year, starting as a carved series in 2018.", [
        "Olamic had been doing Halloween editions since 2016. In 2018 the carved series started, limited to two knives that year, with a titanium pumpkin first. The Alchemist followed in 2019.",
        "The 2021 editions were five one-off carved Buskers, each with that year's blade logo. See the [[Halloween page|halloween/]].",
    ], ["Pumpkin carving, 2018, sold", "The Alchemist, 2019, sold", "Five carved Buskers, 2021, sold"]),
    series_entry("christmas", "Christmas", "swish", 2, "Limit 2 in 2018. Old page hoped it would become a habit.", [
        "Late 2018, carved pieces coated with Pinstriping by Rat. Santa and Santa's Helper were the first two. The page left two spots for 2019.",
    ], ["Santa, 2018", "Santa's Helper, 2018", "Two 2019 spots, listed open then"]),
    series_entry("war-helmets", "War Helmets", "wayfarer-247", 3, "Limit 6. Closed. One of the first official series, 2017.", [
        "Wayfarer 247 only. Historic, national, or cultural skulls in war helmets. Six knives, six finishes, all sold.",
    ], ["No. 1, sold", "No. 2, sold", "No. 3, sold", "No. 4, sold", "No. 5, sold", "No. 6, sold"]),
    series_entry("art-of-war", "Art of War", "soloist", 0, "Limit 7. Closed.", [
        "Fighters the shop wanted remembered. Sold: Spartans, Samurai, Lacedaemon, Viking, and Bogatyr. Open to every model, and finished.",
    ], ["Spartans, sold", "Samurai, sold", "Lacedaemon, sold", "Viking, sold", "Bogatyr, sold"]),
    series_entry("machines-of-time", "Machines of Time", "rainmaker", 1, "Limit 10. Old page: open, barely started.", [
        "Vehicles, ten knives, most of the themes already named. Below the Surface was sold. Still listed: On the Rails, Through the Clouds, On Two Wheels, and others.",
    ], ["Below the Surface, sold", "On the Rails, listed open", "Through the Clouds, listed open", "On Two Wheels, listed open"]),
    series_entry("masters-mind", "Master's Mind", "busker", 2, "Two a year. Andrey chooses everything.", [
        "You do not pick the model, the material, or the picture. Andrey Kolesnikov does, and you see it when it is done. The old page noted that owls are an Olamic mascot and that the Busker was his design. Sailor, 2020, was sold.",
    ], ["Sailor, 2020, sold", "2018, sold", "2019, not available", "Later years were reservation spots"]),
    series_entry("pew-pew-pew", "Pew Pew Pew", "rainmaker-classic", 0, "Limit 13. Old page: open, about three quarters done.", [
        "Bullet holes, and the path a bullet takes. The old copy said the result follows the same rule as the knives. No two are the same. Open to frame locks and liner locks. Riddled Rainmaker was sold.",
    ], ["Riddled Rainmaker, sold"]),
    series_entry("art-homage", "Art Homage", "whippersnapper", 1, "Limit 6. Old page: open, a third done.", [
        "Other people's pictures, cut into metal by hand. The first, late January 2019, was an Art Nouveau portrait after Alphonse Mucha's Sarah Bernhardt. Art Deco was the next named spot. Three styles were the plan, and the shop asked to hear if someone wanted another.",
    ], ["Alphonse Mucha, Art Nouveau, sold", "Art Deco, listed open"]),
    series_entry("six-samurai", "Six Samurai", "swish", 3, "Limit 6. Closed.", [
        "Six knives on the Wayfarer 247, the Swish, and the Soloist. Numbered One through Five, all sold, and a sixth that the old page marked reserved.",
    ], ["One, sold", "Two, sold", "Three, sold", "Four, sold", "Five, sold", "Six, reserved"]),
    series_entry("here-be-dragons", "Here Be Dragons", "whippersnapper", 3, "Limit 7. Old page: open, about two thirds done.", [
        "Dragons across the folders. Sold on the old page: two Whippersnappers, a Wayfarer 247, and a Swish. Three spots were still open.",
    ], ["Whippersnapper 1, sold", "Whippersnapper 2, sold", "Wayfarer 247, sold", "Swish, sold", "Three spots listed open"]),
    series_entry("gilded-creatures", "Gilded Creatures", "wayfarer-247", 6, "Limit 9. Old page: open, about half done.", [
        "Animals, with one gold inlay for the eye so the set is more than a zoo. Sold: panther, eagle, wolf, tiger, and lynx.",
    ], ["Panther, sold", "Eagle, sold", "Wolf, sold", "Tiger, sold", "Lynx, sold"]),
    series_entry("tree-frogs", "Tree Frogs", "whippersnapper", 4, "Limit 3. Closed.", [
        "Three frogs, three models. A Wayfarer 247, a Busker, and a Whippersnapper. All sold.",
    ], ["Wayfarer 247, sold", "Busker, sold", "Whippersnapper, sold"]),
]


def news_entry(slug, date, title, model, body):
    return {"slug": slug, "date": date, "title": title, "model": model, "body": body}


NEWS = [
    news_entry("experiments-with-coatings", "2026-09-04", "Experiments with coatings", "wayfarer-247", [
        "PVD got Olamic a hard black coating, and then showed its limits. It is black, and it does not sit well next to anodizing.",
        "Cerakote and GunKote were the next tests, because both can be almost any color. Cerakote worked, and it was also thick enough to argue with the tolerances on these knives. 2400 Series Gun Kote, from KG Industries, went on thinner and still left the color open.",
        "As of that post the shop was still testing which coating to keep. The finishes already on the knives, Acid Rain and the GunKote carved series among them, are the public part of the same experiment.",
    ]),
    news_entry("books-open-aura", "2025-04-01", "Books open on the all-titanium automatic", "aura", [
        "April 1, 2025: Olamic opened orders on its first automatic, an all-titanium button lock. The announcement pointed people at the model page.",
        "Specs from that page: 3.5 inches of CPM 20CV, 8.5 inches overall, 5 inches closed, 4.4 ounces. The [[Aura page|models/aura/]] has the rest. This preview does not know whether the book is still open. Ask the shop.",
    ]),
    news_entry("silhouette-released", "2024-02-06", "Silhouette chef's knife released", "silhouette", [
        "The Silhouette is a 7.5 inch chef's knife in CPM MagnaCut, hardened to 63.5 to 64 HRC, with a fine satin finish. Overall length is 12 inches. The blade is 0.12 inch thick and 1.625 inch tall.",
        "The first batch has maker-exclusive carbon fiber scales on polished stainless Corby bolts, a crowned tang, a full-length top swedge, and a leather sheath. Weight is 5.9 ounces, 8.1 with the sheath. Each one is serialized.",
    ]),
    news_entry("wayfarer-247cf", "2023-01-13", "Wayfarer 247CF live build", "wayfarer-247", [
        "The 247CF is the Wayfarer 247 with a show side that is not titanium. Olamic used Fatcarbon, for durability and because the sheets are consistent. Blades on these are the later shapes, in CPM S90V.",
        "The ordering page built a picture while you chose. After the order, the shop needed two or three business days. What shipped was meant to match the mockup closely.",
    ]),
    news_entry("whippersnapper-quickforms", "2022-07-31", "Whippersnapper Quickforms", "whippersnapper-bolsterlock", [
        "Quickform was a faster way to order a bolster-lock Whippersnapper without giving up the custom work. Three scale materials: OD green canvas Micarta, burlap Micarta, and twill carbon fiber.",
        "Each Quickform page held hundreds of mockups you could filter. Posted prices were $645 for the Micartas and $745 for carbon fiber. The knife at the end was still a one-off. It was another door, next to Half Baked and Maker's Choice.",
    ]),
    news_entry("fedokume", "2021-10-14", "Fedokume", "wayfarer-247", [
        "Olamic wanted its own patterned metal, something in the neighborhood of Timascus and mokume that the shop could actually use. A 2017 batch worked. They named it Fedokume. The post says the origin of the name is still classified.",
        "The first pattern was tight. Later batches opened the contrast, then added blue and green next to gold and bronze, in glossy and matte finishes. Carry tests were the point of the third round. The color stayed put, which is the failure mode of a lot of fancy metals.",
        "The post frames it as an in-house alternate to mokume, Timascus, and dragonskin, not a coating.",
    ]),
    news_entry("blade-show-west-2021", "2021-10-04", "Blade Show West, Long Beach", "busker", [
        "Blade Show West returned in 2021 after a cancelled 2020, and it moved. The 2018 and 2019 shows had been in Portland. This one was October 8 and 9 at the Long Beach Convention Center, about a four and a half hour drive from Visalia.",
        "Olamic's table was 148, on the left wall after you came in. The same weekend ran on The Olamic Table for people who were not in the building.",
    ]),
    news_entry("new-address", "2021-09-21", "New suite, same building", "wayfarer-247", [
        "After eight years in the building, the shop moved units. Effective October 1, 2021, the address is Olamic Cutlery, Inc., 650 S Bridge Street, Suite A, Visalia, CA 93277. Mail, repairs, and returns still go there.",
    ]),
    news_entry("bolsterlock-announced", "2021-09-06", "Bolster-lock Whippersnapper", "whippersnapper-bolsterlock", [
        "The frame-lock Whippersnapper's first run was ending. The next one kept the size and added an integral front bolster, so the show side could be something other than a full titanium slab.",
        "That is the liner-lock way of building, which the shop had used since 2013. People already on the Whippersnapper list were told they would hear about this version without signing up again.",
    ]),
    news_entry("appetizer-first-taste", "2021-08-26", "First taste of the Appetizer", "appetizer", [
        "Shown on Instagram on August 25, 2021. A non-locking folder just under 4.5 inches overall, blade under 2 inches, with a modular backspacer. The signup asked which spine you wanted: plain, bottle opener, lanyard loop, or carabiner. Orders on the model page opened February 14, 2022, from $295.",
    ]),
    news_entry("antique-entropic", "2021-01-15", "Antique Entropic", "aura", [
        "Entropic, the original finish, came out in summer 2018. Olamic says they were first to it, and for a while they kept it to themselves. Antique Entropic is the later variation: deep rust, a worn texture, and the same unpredictable ground as the first finish.",
        "A brighter subset was called Antique Neon tropic. It combines with rocks sculpting, Acid Rain, Funky Holes, inlays, and the standard hole patterns.",
    ]),
    news_entry("olamic-table", "2020-03-31", "The Olamic Table opens", "wayfarer-247", [
        "IWA OutdoorClassics was the first show to fall off the 2020 calendar, and the rest followed. The Olamic Table was the replacement: a site that ran on the original show dates, with live hangouts and knives posted when the show would have opened.",
        "The research notes for this preview, gathered in September 2026, still point buyers at [[theolamictable.com|https://theolamictable.com/]] and its archives when the main site is between drops.",
    ]),
    news_entry("whippersnapper-launched", "2019-11-11", "Whippersnapper launched", "whippersnapper", [
        "November 11, 2019. Andrey Kolesnikov's follow-up to the Busker, in CPM 20CV, frame lock, with a new 3D clip and the long floating backspacer. The launch post sent people to the model page for the spec chart. The bolster lock came later, in 2021.",
    ]),
    news_entry("exotic-damascus", "2019-07-18", "Bertie Rietveld damascus", "swish", [
        "Olamic picked up a small amount of Bertie Rietveld's damascus at Blade Show and built a matching set. Two patterns: Dragonskin and Nebula. The post tied that steel to the limited Damasteel editions already running on the 247, the Busker, and the Swish.",
    ]),
    news_entry("rainmaker-framelock-announced", "2019-03-29", "Rainmaker frame lock announced", "rainmaker", [
        "The frame-lock Rainmaker was announced as the next model: same DNA as the other frame locks, caged bearings, floating backbar, all titanium, M390, 4 inch blade, 9.75 inches overall, 5.5 inches closed, 0.48 inch handle.",
        "The June 2019 blade note split drop point and harpoon into flat and hollow grinds. Mirror was listed for the hollows.",
    ]),
    news_entry("damasteel", "2019-03-27", "Damasteel on the 247, Busker, and Swish", "busker", [
        "First time Olamic offered Damasteel on the three busiest models, blade and a matching clip. Super Dense Twist, stainless, hardened to 60 HRC. One hundred pieces per model.",
        "The Busker was limited to Semper and Largo. The 247 was offered in all four shapes it had at the time. A titanium clip was the substitute if you did not want the Damasteel one. Small batches also went to Blade HQ, KnifeCenter, DLT Trading, and Lamnia.",
    ]),
]


DEALERS = [
    ("Arkansas", [("A.G. Russell Knives", "2900 S. 26th St, Rogers, AR 72758")]),
    ("Arizona", [("Lee's Cutlery", "")]),
    ("California", [
        ("Nordic Knives", "436 1st St, Solvang, CA 93463"),
        ("Plaza Cutlery", "3333 Bristol St, Costa Mesa, CA 92626"),
        ("EDC Knives", ""),
        ("Williams Cutlery", "14824 Camden Ave, San Jose, CA 95124"),
        ("Recon 1", "19425 Ventura Blvd, Tarzana, CA 91356"),
        ("Steel Addiction Custom Knives", ""),
        ("Sticky Rick Knives", ""),
        ("We Be Knives", "Pier 39, San Francisco, CA 94133"),
        ("Urban EDC Supply", ""),
        ("Blade Junkee", ""),
    ]),
    ("Florida", [("Hollow Grind", ""), ("Arizona Custom Knives", ""), ("Blade Art", "")]),
    ("Illinois", [
        ("GP Knives", "2230 Liebler Rd, Troy, IL 62294"),
        ("ROS Arms", ""),
        ("Windy City Knives", ""),
    ]),
    ("Iowa", [
        ("North To South Knives", ""),
        ("Outdoors & More", "115 3rd Avenue West, Cresco, IA 51236"),
    ]),
    ("Maryland", [
        ("Ye Ole Cutlery & Gift Shop", "5015 St. Leonard Rd, St. Leonard, MD 20685"),
        ("Red Hill Tactical", "13024 Pennsylvania Ave, Hagerstown, MD 21742"),
    ]),
    ("Massachusetts", [("Perry Knife Works", ""), ("Knife Legends", "")]),
    ("Nevada", [("PVK Vegas", "3729 S Las Vegas Blvd, Las Vegas, NV 89109")]),
    ("New York", [
        ("Empire Outfitters", ""),
        ("Paragon Sports", "867 Broadway at 18th St, New York, NY 10003"),
        ("Stabbers Steel Connection", ""),
    ]),
    ("North Carolina", [("Knife Purveyor", "")]),
    ("Ohio", [("River's Edge Cutlery", "3977 Trueman Blvd, Hilliard, OH 43026")]),
    ("Pennsylvania", [("Art Knives / Fred Eisen Leather", "85 S Main St, New Hope, PA 18938")]),
    ("Tennessee", [
        ("Fort Henry Custom Knives", ""),
        ("Smoky Mountain Knife Works", "2320 Winfield Dunn Parkway, Sevierville, TN 37876"),
    ]),
    ("Utah", [
        ("Blade HQ", "400 S 1000 E, Ste E1, Lehi, UT 84043"),
        ("BladeOps", "1352 W 7800 S, West Jordan, UT 84088"),
    ]),
    ("Virginia", [("Knife Center", "")]),
    ("Wisconsin", [("DLT Trading", "2900 Cleveland Ave, Marinette, WI 54143")]),
    ("Russia", [("Rezat.ru", "9 Vetoshnyi Pereylok, Moscow")]),
    ("Finland", [("Lamnia", "Myllymäenkatu 12, Lappeenranta 53550")]),
    ("Hong Kong", [("Supreme Co Tactical", "56 Dundas St, Mong Kok")]),
    ("Australia", [("Granbers / Kizlyar Knife Store", "5/75 Miguel Road, Bibra Lake, WA 6163")]),
    ("Thailand", [("CFF Thailand", "Charadmuang Road, Bangkok")]),
]


def model_by(slug):
    for model in MODELS:
        if model["slug"] == slug:
            return model
    raise KeyError(slug)


def rotate(images, start, count):
    if not images:
        return []
    total = len(images)
    count = min(count, total)
    return [images[(start + index) % total] for index in range(count)]


def pretty_date(iso: str) -> str:
    months = "January February March April May June July August September October November December".split()
    year, month, day = iso.split("-")
    return f"{months[int(month) - 1]} {int(day)}, {year}"


def head(kicker, title, lede, prefix) -> str:
    return (
        '<header class="page-head">'
        f'<p class="kicker">{esc(kicker)}</p>'
        f"<h1>{esc(title)}</h1>"
        '<hr class="heat">'
        f'<p class="lede">{inline(lede, prefix)}</p>'
        "</header>"
    )


def card(model, prefix, lazy=True) -> str:
    image = model["images"][0]
    loading = ' loading="lazy"' if lazy else ""
    href = esc(prefix + f"models/{model['slug']}/")
    return (
        f'<a class="model-card" href="{href}" data-tags="{esc(model["tags"])}">'
        f'<img src="{esc(prefix + image["src"])}" width="{image["w"]}" height="{image["h"]}" alt="{esc(image["alt"])}"{loading}>'
        "<div>"
        f'<p class="meta">{esc(model["kicker"])}</p>'
        f'<h3>{esc(model["name"])}</h3>'
        f'<p>{esc(model["summary"])}</p>'
        "</div></a>"
    )


def attach_images() -> None:
    jobs = []
    plans = []
    for model in MODELS:
        files = pick(
            model["sources"],
            count=8,
            hero=model.get("hero"),
            window=model.get("slice"),
        )
        if not files:
            raise SystemExit(f"no images for {model['slug']}")
        pairs = []
        for src in files:
            dest = SITE / "media" / model["slug"] / f"{src.stem}.jpg"
            pairs.append((src, dest))
            jobs.append((src, dest))
        plans.append((model, pairs))
    sizes = prepare_images(jobs)
    for model, pairs in plans:
        images = []
        total = len(pairs)
        for index, (_, dest) in enumerate(pairs, start=1):
            width, height = sizes[dest]
            images.append(
                {
                    "src": f"media/{model['slug']}/{dest.name}",
                    "w": width,
                    "h": height,
                    "alt": f"Olamic {model['name']}, photograph {index} of {total}",
                }
            )
        model["images"] = images
        print(f"  {model['slug']}: {total} photos")


def page_home() -> None:
    prefix = ""
    hero_model = model_by("wayfarer-247")
    hero = hero_model["images"][0]
    bench_slugs = ["busker", "whippersnapper", "wayfarer-247", "swish", "rainmaker", "soloist", "aura", "silhouette"]
    bench = []
    for slug in bench_slugs:
        model = model_by(slug)
        image = model["images"][0]
        bench.append(
            "<li><a href=\""
            + esc(f"models/{slug}/")
            + "\">"
            + f'<img src="{esc(image["src"])}" width="{image["w"]}" height="{image["h"]}" alt="{esc(image["alt"])}" loading="lazy">'
            + f"<strong>{esc(model['name'])}</strong><span>{esc(model['kicker'])}</span></a></li>"
        )
    cards = "\n".join(card(model, prefix) for model in MODELS)
    news_items = []
    for item in NEWS[:5]:
        news_items.append(
            "<li><a href=\""
            + esc(f"news/{item['slug']}/")
            + "\">"
            + f"<time datetime=\"{esc(item['date'])}\">{esc(pretty_date(item['date']))}</time>"
            + f"<strong>{esc(item['title'])}</strong></a></li>"
        )
    body = f"""
    <div class="wrap hero">
      <div class="hero-copy">
        <p class="kicker">Visalia, California · since 2010</p>
        <h1>Never the same.</h1>
        <hr class="heat">
        <p class="lede">Olamic Cutlery is the Solomonik family shop. Every knife is serialized. The finish changes from one serial to the next, on purpose.</p>
        <div class="hero-actions">
          <a class="btn" href="folding-knives/">The knives</a>
          <a class="btn ghost" href="how-to-order/">How to order</a>
        </div>
      </div>
      <figure class="hero-figure">
        <img src="{esc(hero["src"])}" width="{hero["w"]}" height="{hero["h"]}" alt="{esc(hero["alt"])}" fetchpriority="high">
      </figure>
    </div>
    <section class="section">
      <div class="wrap">
        <p class="kicker">On the bench</p>
        <h2>Eight ways the line changes size.</h2>
        <ul class="bench">{''.join(bench)}</ul>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <p class="kicker">Fourteen models</p>
        <h2>From a non-locking Appetizer to a 7.5 inch chef's knife.</h2>
        <p class="lede">Frame locks are fitted in Visalia after the precise parts are machined. The early customs, the Wayfarers and the Rainmaker and the Gambit, are still ground without a CNC.</p>
        <div class="model-grid" style="margin-top:1.5rem">{cards}</div>
      </div>
    </section>
    <section class="section">
      <div class="wrap split">
        <figure class="quote">
          <blockquote>
            <p>What an amazing knife. I was blown away the first time I fired it open.</p>
          </blockquote>
          <footer>Everyday Commentary on the Wayfarer 247, September 2016. The score was 19 out of 20. <a href="https://www.everydaycommentary.com/www.everydaycommentary.com//2016/09/olamic-cutlery-wayfarer-247-review.html" rel="noopener noreferrer">Read the review</a>.</footer>
        </figure>
        <div class="stack">
          <div>
            <h3>Serialized</h3>
            <p>The name means something that lasts. The mark is an infinity. The warranty is lifetime, and it follows the knife past the first owner.</p>
          </div>
          <div>
            <h3>Finished by hand</h3>
            <p>Hole patterns, carving, anodizing, inlays. Most of that cannot be machined, which is why two 247s with the same blade shape still do not match.</p>
          </div>
          <div>
            <h3>Spa service</h3>
            <p>Send it back. The shop replaces wear parts, sets the detent and the lock, cleans it, and oils it. Sharpening is included unless you say otherwise.</p>
          </div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap split">
        <div>
          <p class="kicker">Andrey Kolesnikov</p>
          <h2>Hand carved, one knife in a series.</h2>
          <div class="prose">
            <p>Since December 2016 the carving has been Andrey's. Each series has a theme and a finite count. When the count is done, the series closes.</p>
            <p><a href="hand-carved/">The carved series</a></p>
          </div>
        </div>
        <div>
          <p class="kicker">News</p>
          <ul class="news-list">{''.join(news_items)}</ul>
          <p style="margin-top:1rem"><a href="news/">All news</a></p>
        </div>
      </div>
    </section>
    """
    write_page(
        "index.html",
        "Olamic Cutlery",
        "Olamic Cutlery in Visalia. Serialized folders and a chef's knife. Never the same.",
        "",
        body,
    )


def page_models_index() -> None:
    prefix = "../"
    folders = [model for model in MODELS if model["slug"] != "silhouette"]
    folders = sorted(folders, key=lambda model: BLADE_IN[model["slug"]])
    rows = []
    for model in folders:
        width = round(BLADE_IN[model["slug"]] / 4.125 * 100)
        rows.append(
            "<tr>"
            f'<td><a href="{esc(prefix)}models/{model["slug"]}/">{esc(model["name"])}</a></td>'
            f"<td>{esc(model['kicker'])}</td>"
            f"<td>{BLADE_IN[model['slug']]:.3g} in<span class=\"bar\" style=\"width:{width}%\"></span></td>"
            "</tr>"
        )
    cards = "\n".join(card(model, prefix) for model in MODELS)
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Knives", None)], prefix)}
      {head("The line", "Folding knives", "Fourteen models in the current archive, counted the way the old site counted them, chef's knife included.", prefix)}
      <div data-filter-root>
        <search>
          <label class="kicker" for="knife-search">Search models</label>
          <input id="knife-search" type="search" name="q" placeholder="247, MagnaCut, liner lock">
        </search>
        <div class="chips" role="group" aria-label="Filter">
          <button type="button" data-chip="all" aria-pressed="true">All</button>
          <button type="button" data-chip="front" aria-pressed="false">Front flipper</button>
          <button type="button" data-chip="frame" aria-pressed="false">Frame lock</button>
          <button type="button" data-chip="liner" aria-pressed="false">Liner lock</button>
          <button type="button" data-chip="auto" aria-pressed="false">Automatic</button>
          <button type="button" data-chip="kitchen" aria-pressed="false">Kitchen</button>
          <button type="button" data-chip="slipjoint" aria-pressed="false">Non-locking</button>
        </div>
        <p data-empty hidden>Nothing in the line matches that.</p>
        <div class="model-grid">{cards}</div>
      </div>
      <section class="section">
        <h2>Size, small to large.</h2>
        <p class="lede">Blade length used for the bar. The Silhouette is a 7.5 inch chef's knife and is left off the bar so the folders can be compared.</p>
        <table class="ladder">
          <thead><tr><th>Model</th><th>Lock</th><th>Blade</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </section>
    </div>
    """
    write_page("folding-knives/index.html", "Folding knives", "Every Olamic model in this preview, with a size comparison.", "knives", body)


def page_model(model) -> None:
    rel = f"models/{model['slug']}/index.html"
    prefix = "../../"
    features = "".join(f"<li>{esc(item)}</li>" for item in model["features"])
    quote = ""
    if model.get("quote"):
        text, cite, url = model["quote"]
        quote = (
            '<section class="section"><div class="wrap"><figure class="quote"><blockquote><p>'
            + esc(text)
            + "</p></blockquote><footer>"
            + esc(cite)
            + f' <a href="{esc(url)}" rel="noopener noreferrer">Source</a></footer></figure></div></section>'
        )
    related = []
    for slug in model["related"]:
        other = model_by(slug)
        related.append(f'<a href="{esc(prefix)}models/{slug}/">{esc(other["name"])}</a>')
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Knives", "folding-knives/"), (model["name"], None)], prefix)}
      {head(model["kicker"], model["name"], model["lede"], prefix)}
      <div class="split">
        <div class="prose">
          {paras(model["story"], prefix)}
          <h2>On the knife</h2>
          <ul>{features}</ul>
        </div>
        <div>
          <h2>Specs</h2>
          {specs_table(model["specs"])}
        </div>
      </div>
      <section class="section">
        <h2>From the bench</h2>
        {gallery(model["images"], prefix, model["caption"], priority=True)}
      </section>
    </div>
    {quote}
    <section class="section">
      <div class="wrap">
        <h2>Ask about a {esc(model["name"])}</h2>
        <p class="lede">This form does not send. It is here so the page has the same shape as the old build request. Email <a href="mailto:team@olamiccutlery.com">team@olamiccutlery.com</a> to actually start one.</p>
        <form class="form" data-form style="margin-top:1rem">
          {form_fields(f'''
            <label>Topic
              <select name="topic">
                <option value="order">Build request</option>
                <option value="support">Question</option>
              </select>
            </label>
            <input type="hidden" name="model" value="{esc(model["name"])}">
          ''')}
        </form>
        <h2 style="margin-top:2.5rem">Next to it</h2>
        <div class="related">{''.join(related)}</div>
      </div>
    </section>
    """
    write_page(rel, model["name"], model["summary"], "knives", body)


def page_series_index() -> None:
    prefix = "../"
    cards = []
    for item in SERIES:
        image = rotate(model_by(item["model"])["images"], item["offset"], 1)[0]
        cards.append(
            f'<a class="model-card" href="{esc(prefix)}series/{item["slug"]}/">'
            f'<img src="{esc(prefix + image["src"])}" width="{image["w"]}" height="{image["h"]}" alt="" loading="lazy">'
            f'<div><p class="meta">{esc(item["status"])}</p><h3>{esc(item["title"])}</h3>'
            f'<p>{esc(item["body"][0][:140])}…</p></div></a>'
        )
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Series", None)], prefix)}
      {head("Carved and themed", "Series", "Finite sets. When the count is done, the series closes. Status lines are how the old site left them, not a promise that a spot is open today.", prefix)}
      <div class="model-grid">{''.join(cards)}</div>
      <p class="lede" style="margin-top:1.5rem">Andrey Kolesnikov has done the carving since December 2016. <a href="{esc(prefix)}hand-carved/">Read the hand-carved note</a>.</p>
    </div>
    """
    write_page("series/index.html", "Series", "Olamic carved and themed series, from the old site.", "series", body)


def page_series(item) -> None:
    rel = f"series/{item['slug']}/index.html"
    prefix = "../../"
    images = rotate(model_by(item["model"])["images"], item["offset"], 5)
    pieces = "".join(f"<li>{esc(piece)}</li>" for piece in item["pieces"])
    host = model_by(item["model"])
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Series", "series/"), (item["title"], None)], prefix)}
      {head(item["status"], item["title"], item["body"][0], prefix)}
      <div class="prose">{paras(item["body"][1:], prefix)}</div>
      <section class="section">
        <h2>Pieces named on the old page</h2>
        <ul class="piece-list">{pieces}</ul>
      </section>
      <section class="section">
        <h2>Photographs</h2>
        <p class="lede">These are {esc(host["name"])} builds from the shop archive, used because this series was cut on that model. They are not labeled as the named pieces above.</p>
        {gallery(images, prefix, None, priority=True)}
      </section>
    </div>
    """
    write_page(rel, item["title"], item["body"][0], "series", body)


def page_news_index() -> None:
    prefix = "../"
    items = []
    for item in NEWS:
        items.append(
            "<li><a href=\""
            + esc(f"{item['slug']}/")
            + "\"><time datetime=\""
            + esc(item["date"])
            + "\">"
            + esc(pretty_date(item["date"]))
            + "</time><span><strong>"
            + esc(item["title"])
            + "</strong><br>"
            + esc(item["body"][0])
            + "</span></a></li>"
        )
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("News", None)], prefix)}
      {head("From the shop", "News", "Announcements rebuilt from the old site. Spam that had been injected into a few posts is not here.", prefix)}
      <ul class="news-list">{''.join(items)}</ul>
    </div>
    """
    write_page("news/index.html", "News", "Olamic Cutlery news, from the shop's own posts.", "news", body)


def page_news(item) -> None:
    rel = f"news/{item['slug']}/index.html"
    prefix = "../../"
    images = rotate(model_by(item["model"])["images"], 0, 3)
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("News", "news/"), (item["title"], None)], prefix)}
      <header class="page-head">
        <p class="kicker"><time datetime="{esc(item["date"])}">{esc(pretty_date(item["date"]))}</time></p>
        <h1>{esc(item["title"])}</h1>
        <hr class="heat">
      </header>
      <div class="prose">{paras(item["body"], prefix)}</div>
      <section class="section">
        {gallery(images, prefix, "Shop photography from the related model, not necessarily the knife in the post.", priority=True)}
      </section>
    </div>
    """
    write_page(rel, item["title"], item["body"][0], "news", body)


def prose_page(rel, current, kicker, title, lede, description, paragraphs, extra="") -> None:
    prefix = "../" * rel.count("/")
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), (title, None)], prefix)}
      {head(kicker, title, lede, prefix)}
      <div class="prose">{paras(paragraphs, prefix)}</div>
      {extra.replace("__P__", prefix)}
    </div>
    """
    write_page(rel, title, description, current, body)


def page_about() -> None:
    prose_page(
        "about/index.html",
        "about",
        "The family",
        "About",
        "A family company, started in 2010 by Eugene Solomonik and his father Ilya.",
        "How Olamic Cutlery started, and how the knives are built in Visalia.",
        [
            "The name means something that lasts through eternity. That is why the mark is an infinity, why every knife ships with a serial, and why the warranty and the spa service are lifetime.",
            "They learned knives in Karelia, in northwestern Russia. The first work was hand-forged high-carbon vanadium damascus fixed blades, from a small Russian shop. Fixed blades are still made there. The damascus is a proprietary mix the shop calls HCVD. When a folder gets an HCVD blade, the blank is forged in Russia and finished in California.",
            "Folders started in 2013. Olamic brought in ABS Master Smith Michael Vagnino and set up a small shop in Visalia, where he lives. The aim was old handwork on modern titanium frames.",
            "The Wayfarer Classic was the first of those folders, at Blade Show 2013. Then the Wayfarer Compact, the Rainmaker, and the Gambit. Those four are handmade. No CNC. The old about page put the number of possible custom builds over ten million, and said that is the only way to keep the rule: never the same.",
            "In 2016 they wanted a tough everyday knife and designed the Wayfarer 247. To make it hold up, and to make the price competitive, the parts that have to be precise are pre-machined. The rest is still done by hand in Visalia, because the finishes people actually buy cannot be machined.",
            "Design credits, from the shop and from reviewers who have asked: Eugene and Michael Vagnino on the first Wayfarer, Alexander Birykov on the Rainmaker and the Swish, Serge Panchenko on the Gambit, Andrey Kolesnikov on the Busker, the Whippersnapper, the Appetizer, and every carved frame since December 2016.",
        ],
    )


def page_support() -> None:
    extra = """
    <form class="form" data-form style="margin-top:1.5rem">
      __FIELDS__
    </form>
    """.replace("__FIELDS__", form_fields("""
      <label>Topic
        <select name="topic">
          <option value="support">Question</option>
          <option value="service">Spa, repair, or warranty</option>
        </select>
      </label>
      <label>Serial, if you have it<input name="serial" autocomplete="off"></label>
    """))
    prose_page(
        "support/index.html",
        "support",
        "After it ships",
        "Support",
        "Lifetime warranty on Olamic knives. If something is wrong, write before you ship.",
        "Warranty, spa service, and how to reach Olamic support in Visalia.",
        [
            "Every Olamic knife is covered by the [[lifetime warranty|warranty/]] against defects in materials or construction. The warranty follows the knife. It is not limited to the first owner. It does not cover abuse, accidents, loss, theft, or work someone else did to the knife.",
            "Spa service is free. At the shop's discretion it can include a new lockbar insert, detent ball, pivot, screws, clip ball, or bearings. They will also reset detent strength, lock engagement, and centering, then clean the knife, oil it, and look it over. Sharpening is part of the spa unless you ask them not to. Upgrades get a spa pass by default.",
            "Email [[support@olamiccutlery.com|mailto:support@olamiccutlery.com]]. The ship-to address is Olamic Support, 650 S Bridge St, Suite A, Visalia, CA 93277. Use a service with tracking. Do not ship a knife until a service request is in. International shippers should ask about the shop's discounted rates before they buy a label.",
            "The old support page also linked assembly notes for the Swish and the Busker. Those steps are not in the export used here, so this preview does not invent them. Ask support for the current sheet.",
            "For a customization, a trade-in, or a plain question, use the note below or the [[service form|service/]].",
        ],
        extra,
    )


def page_warranty() -> None:
    prose_page(
        "warranty/index.html",
        "support",
        "The policy on the old site",
        "Warranty",
        "Lifetime coverage for defects, a short return window, and a free spa.",
        "Olamic lifetime warranty, return fees, and spa service, from the old warranty page.",
        [
            "All Olamic products are covered for life against defects in materials or construction. The warranty does not cover inappropriate use, aftermarket modification, accidents, loss, or theft. If the shop agrees a knife is defective and covered, they repair or replace it at their discretion. Third-party modification voids the warranty. Coverage is not limited to the original owner.",
            "Custom builds: a return could be requested within 72 hours of delivery. The knife had to be unused, unsharpened, unmodified, still fully assembled, and sent back with everything that arrived with it. The shop inspected it and then replied. The restocking fee was 25 percent. Refunds were processed within three business days on the original payment method.",
            "Pre-made knives and other store items used the same 72 hour window and the same unused, complete, unsharpened, unmodified, still-assembled rule. The restocking fee on those was 10 percent. Same three-day refund timing.",
            "Spa service is free for Olamic knives. If the shop decides a part needs it, they replace the lockbar insert, detent ball, pivot barrel, screws and pivots, the pocket-clip retention ball, or the bearings and washers. They can also adjust detent strength, lock engagement, and blade centering. Cleaning, fresh oil, and a full inspection are standard. The spa includes sharpening unless you ask them not to sharpen it. Knives that arrive for an upgrade or a customization get the spa anyway.",
            "Ship only after you [[open a service request|service/]]. Questions go to [[support@olamiccutlery.com|mailto:support@olamiccutlery.com]].",
        ],
    )


def page_contact() -> None:
    extra = """
    <div class="two" style="margin-top:2rem">
      <form class="form" data-form>
        __FIELDS__
      </form>
      <div class="stack">
        <p><strong>Sales.</strong> <a href="mailto:team@olamiccutlery.com">team@olamiccutlery.com</a></p>
        <p><strong>Support.</strong> <a href="mailto:support@olamiccutlery.com">support@olamiccutlery.com</a></p>
        <p><strong>Shop.</strong> 650 S Bridge St, Suite A, Visalia, CA 93277, USA</p>
        <p>The old contact page also pointed at Instagram, Facebook, and Twitter, and said you could write Eugene or Ilya through the form. The public profiles that have traveled with the shop are <a href="https://www.instagram.com/olamic/" rel="noopener noreferrer">Instagram</a>, <a href="https://www.facebook.com/OlamicCutlery" rel="noopener noreferrer">Facebook</a>, and <a href="https://twitter.com/Olamiccutlery" rel="noopener noreferrer">X</a>.</p>
        <p>To see the knives in person, check the <a href="__P__trade-shows/">show list</a>. It is a history, not this year's calendar.</p>
      </div>
    </div>
    """.replace("__FIELDS__", form_fields("""
      <label>Topic
        <select name="topic">
          <option value="order">Sales and orders</option>
          <option value="support">Support</option>
          <option value="dealer">Dealers</option>
          <option value="press">Everything else</option>
        </select>
      </label>
    """))
    prose_page(
        "contact/index.html",
        "support",
        "Visalia",
        "Contact",
        "Sales, support, and the street address. The form on this preview stays in your browser.",
        "Contact Olamic Cutlery in Visalia.",
        [
            "For a knife you already own, start with [[support|support/]] and the warranty page. Email support@olamiccutlery.com, or use the note here. Fill out a [[service request|service/]] before you put a knife in a box.",
            "For a build, use the [[build assistant|build-assistant/]] to get the words straight, then email team@olamiccutlery.com. The old site answered build forms in about two business days.",
        ],
        extra,
    )


def page_dealers() -> None:
    prefix = "../"
    blocks = []
    for region, shops in DEALERS:
        items = []
        for name, address in shops:
            addr = f"<span>{esc(address)}</span>" if address else ""
            items.append(f"<li>{esc(name)}{addr}</li>")
        blocks.append(f"<div><h3>{esc(region)}</h3><ul>{''.join(items)}</ul></div>")
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Dealers", None)], prefix)}
      {head("Where they have been sold", "Dealers", "The dealer list from the old site, grouped the way that page grouped it. A name here is not a promise the shop still stocks Olamic.", prefix)}
      <div class="dealer-grid">{''.join(blocks)}</div>
      <p class="lede" style="margin-top:2rem">{inline("If you sell knives and want the line, use [[become a dealer|become-a-dealer/]].", prefix)}</p>
    </div>
    """
    write_page("dealers/index.html", "Dealers", "Olamic Cutlery dealers as listed on the old site.", "about", body)


def page_simple_forms() -> None:
    page_about()
    page_support()
    page_warranty()
    page_contact()
    page_dealers()
    prose_page(
        "become-a-dealer/index.html",
        "about",
        "Stock the line",
        "Become a dealer",
        "Olamic has said it is open to new shops. The answer includes terms, discounts, and what they can actually ship.",
        "How to ask Olamic about a dealer account.",
        [
            "The old page put it this way. The catalog covers a wide range of prices and styles, and the motto does not stop at the knife. Product, support, and how partners get treated are all part of the same rule.",
            "A reply was supposed to include dealership conditions, the discount structure, and inventory. Because the knives vary so much, the shop also talked about exclusives and small runs.",
            "Write team@olamiccutlery.com with the note below. Say what you sell and where.",
        ],
        """
        <form class="form" data-form style="margin-top:1.5rem">
        """
        + form_fields("""
          <label>Topic
            <select name="topic"><option value="dealer">Dealer inquiry</option></select>
          </label>
          <label>Shop name<input name="shop" required></label>
          <label>City<input name="city" autocomplete="address-level2"></label>
        """),
    )
    prose_page(
        "trade-shows/index.html",
        "about",
        "Tables they have stood behind",
        "Trade shows",
        "The last schedule published on the old site was 2021. Below that is every show the page said they had done.",
        "Olamic Cutlery show history from the old trade-show page.",
        [
            "2021, as printed: California Custom Knife Show in Anaheim, October 23 to 24. Blade Show West in Long Beach, October 8 to 9, table 148. USN Gathering G12 in Las Vegas, September 3 to 4. Blade Show in Atlanta, June 4 to 6.",
            "From April 2020 the shop also ran virtual shows on The Olamic Table during the dates of cancelled events, and later mirrored in-person shows there for people who could not travel. The archive is at [[theolamictable.com|https://theolamictable.com/]].",
            "Years the old page listed. Blade Show in Atlanta, 2012 through 2019 and 2021. Blade Show West in Portland, 2018 and 2019. SoCal Blades in Pasadena, 2011 through 2018. Oregon Knife Collectors in Eugene, 2013 through 2016 and 2018 and 2019. Antique Arms in Las Vegas, 2011 through 2015. IWA in Nuremberg, 2018 and 2019. New York Custom Knife Show and the East Coast Custom Knife Show in Jersey City, most years from 2011 or 2012 through 2019. Las Vegas Custom Knife Show, 2018 and 2019. California Custom Knife Show in Anaheim, 2013 through 2020. SICAC in Paris, 2016, 2018, 2019. Spirit of Steel in Knoxville, 2011. A.G. Russell's show in Rogers, 2011 through 2013. USN Gathering in Las Vegas, 2013 through 2019 and 2021. PKA in Denver, 2012 through 2016.",
            "This page is that record. It is not a 2026 calendar. Ask the shop, or watch the news page, before you drive.",
        ],
    )
    prose_page(
        "trade-in/index.html",
        "support",
        "Wayfarer 247",
        "Trade-in",
        "A base 247 could be sent in. You paid the difference between its original MSRP and the knife you wanted.",
        "How the Olamic Wayfarer 247 trade-in program worked.",
        [
            "The old page called it the first program of its kind for the 247. What you paid, and where you bought it, did not matter. Trade-in value was the original MSRP. Their example: a plain first-run 247 at a $375 MSRP against a knife listed at $545 meant you sent the knife and paid $170.",
            "The knife you sent had to be complete, with no third-party modifications. Anodizing was allowed if Olamic had done it. You picked from knives they marked for the program.",
            "Eligible MSRPs on that page, Elmax blade: matte or stonewash $375, PVD stonewash $395, sculpted $445, sculpted with PVD stonewash $445. M390 blade: $395, $415, $465, and $465 for the same four finishes.",
            "It did not run all year. The printed window was August 1 through September 15. Eligible looks included a plain satin-blade matte handle, any sculpted handle, a base backbar and clip with no holes, non-PVD sculpted handles, and stealth or sculpted knives with anodized hardware.",
            "The program's current status is not in this archive. Email [[team@olamiccutlery.com|mailto:team@olamiccutlery.com]] before you ship a knife.",
        ],
        """
        <form class="form" data-form style="margin-top:1.5rem">
        """
        + form_fields("""
          <label>Topic<select name="topic"><option value="order">Trade-in question</option></select></label>
          <label>Your 247 serial<input name="serial"></label>
        """),
    )
    prose_page(
        "upgrade/index.html",
        "support",
        "Change the knife you have",
        "Upgrades",
        "If the trade-in window is closed, the old upgrade page was the other route. New finish, new clip, new backspacer.",
        "Ways Olamic would change a knife you already own.",
        [
            "The trade-in is the exchange. If it is not running, or nothing on the list is the knife you want, the upgrade page said to write and describe the change. A third route was the parts shop, for work you would do yourself.",
            "Backspacer. The standard one is titanium. They would anodize it, refinish it, sculpt it, or add filework. A style that already existed on another knife could usually be added to yours.",
            "Handle. A base Swish or 247 with a plain handle could take a new finish, with or without one of the speed-hole patterns. Anodizing on top of that was enough to make it a different object.",
            "Pocket clip. Titanium, so it can be refinished or replaced. Replacements were case by case.",
            "Molten is a carved, anodized titanium finish with a lot of texture. The page called out the 247 and the Swish as the handles it suits.",
            "Acid Rain has been an Olamic finish since 2016. They do not use a fixed setup, so each one comes out a little different, and it can sit on top of other finishes.",
            "Kinetic was the new finish when that page was written. It is for titanium frames and bolsters, and the pattern reads like grain.",
        ],
    )
    prose_page(
        "half-baked/index.html",
        "knives",
        "Almost done",
        "Half baked builds",
        "The carving, the sculpting, and the weight relief were already chosen. You picked color and finish. Then it shipped in a couple of days.",
        "Olamic half baked builds, the middle path between a full custom and a knife on the shelf.",
        [
            "Half Baked was a way to order a Busker, a 247, or a Swish that was already most of the way to a specific knife. Olamic had decided the carving, sculpting, and weight reduction. The buyer chose the direction of the color and the finish. After the details were confirmed, the knife shipped in two business days.",
            "The old page grouped the work as inlays, sculpted, Acid Rain, hole patterns, and faux bolster. It also said the offer would open a few times a year, with an email list when new knives were posted.",
            "Four Wayfarer 247 half-baked pieces were on the page as examples, serials 22656, 22660, 22661, and 22662. They were marked sold. This preview does not have them in stock and does not take payment.",
            "The bolster-lock Whippersnapper used the same idea later. The scale was chosen. You finished the rest, or you picked Maker's Choice. Quickforms were the even faster cousin, with hundreds of mockups per scale material.",
        ],
    )
    prose_page(
        "how-to-order/index.html",
        "knives",
        "Three doors",
        "How to order",
        "A full build, a half-baked knife, or something already finished. The old site separated them on purpose.",
        "How ordering worked on the old Olamic site.",
        [
            "Frame locks. The 247, Busker, Soloist, Rainmaker, Swish, and Whippersnapper each had a build form. You looked at the [[build assistant|build-assistant/]] first. The shop wrote back within two business days. The Whippersnapper frame-lock books were closed when that page was current. The bolster lock replaced them.",
            "Liner locks. Wayfarer Classic, Wayfarer Compact, and Rainmaker Classic are full custom, and the option list was too long for a form. You described the knife. The old page had the books opening at the end of October 2021. Treat that date as history.",
            "Half baked. A narrower set of choices on a knife that already had a direction. A couple of days to finish once you chose. The [[half baked page|half-baked/]] explains it.",
            "Ready to ship. Experimental builds, the first of a new idea, or a knife that simply came out well. The old shop page mixed those with a sold archive. When the main site has been in maintenance, finished knives have been posted on [[The Olamic Table|https://theolamictable.com/]].",
            "Nothing on this preview charges a card. Email [[team@olamiccutlery.com|mailto:team@olamiccutlery.com]].",
        ],
    )
    prose_page(
        "build-your-own/index.html",
        "knives",
        "Tell them the knife",
        "Build your own",
        "The old custom-request page, before the longer forms existed. Describe it. They answer in a few days.",
        "Request a custom Olamic build.",
        [
            "The page admitted the obvious problem. There are millions of configurations, and a form that lists all of them is a project by itself. Until that form was done, you looked at the galleries and wrote down what you actually wanted.",
            "After the first note, the shop talked through the build and locked the details. Lead time depends on the model and on how much handwork you asked for. A confirmed request got a delivery window.",
            "Use the assistant if you want the vocabulary, then send the paragraph to the shop. The box below only keeps it on this computer.",
        ],
        """
        <form class="form" data-form style="margin-top:1.5rem">
        """
        + form_fields("""
          <label>Topic<select name="topic"><option value="order">Custom build</option></select></label>
          <label>Model<input name="model" placeholder="Wayfarer 247, Busker, Classic..."></label>
        """),
    )
    prose_page(
        "service/index.html",
        "support",
        "Before you ship",
        "Service",
        "Spa, repair, warranty, upgrade. Write first. Then send the knife to Visalia.",
        "Olamic customize and repair request.",
        [
            "Ship service work to Olamic Support, 650 S. Bridge St, Unit A, Visalia, CA 93277. Use tracking. Ask before you buy an international label. Do not ship until this request is actually in the shop's hands. The form on this page is a preview and does not file one.",
            "Say what you want done, the serial, and whether the knife has been taken apart or sharpened by anyone else. Third-party work can void the warranty. Anodizing that Olamic did does not.",
        ],
        """
        <form class="form" data-form style="margin-top:1.5rem">
        """
        + form_fields("""
          <label>Topic
            <select name="topic">
              <option value="service">Spa service</option>
              <option value="service">Warranty repair</option>
              <option value="service">Upgrade or customization</option>
            </select>
          </label>
          <label>Serial<input name="serial" required></label>
          <label>Model<input name="model" required></label>
        """),
    )
    prose_page(
        "hand-carved/index.html",
        "series",
        "Since December 2016",
        "Hand carved",
        "Andrey Kolesnikov cuts the frames. The series are finite. Original work, in titanium, which is an odd thing to carve.",
        "Olamic hand carved series and Andrey Kolesnikov.",
        [
            "Andrey Kolesnikov, born in 1960, lives in Russia. He has been around knives, functional art, and metal since he was a kid. He trained as a radio engineer and made the hobby the job in 1991. Miniatures, swords, and the Busker. He has worked only for Olamic since December 2016, and the carving below that date on these knives is his. The old page pointed at his Instagram, @knifemaster60.",
            "Carved knives are one-offs inside a limited series. A theme ties the set together. When the number is reached, the series closes. Some knives on the old pages were finished and for sale. Some open spots had a theme already. Some did not, and you could suggest one. The shop asked you to read the ordering rules first, so the suggestion did not pin the artist down.",
            "The [[series index|series/]] is the whole list from the old site, from Jazzy Buskers and War Helmets through Tree Frogs.",
        ],
    )
    prose_page(
        "halloween/index.html",
        "series",
        "Since 2016",
        "Halloween",
        "A themed blade logo every year. In 2021, five carved Buskers instead of one centerpiece.",
        "Olamic Halloween editions, 2016 through the 2021 carved Buskers.",
        [
            "Halloween editions go back to 2016. The method changed with the catalog. First it was scale colors on the liner locks. Then in-house GunKote opened more of the palette. In 2019 and 2020 one hand-carved knife was the centerpiece, and it was the one people wanted, and there was only one.",
            "In 2021 they made all of them centerpieces. Five one-off carved Buskers, numbered 0/4 through 4/4 on the old page, all marked sold. Each product page let you pick that year's blade logo, and the shop lasered it in the usual spot before the knife shipped.",
            "The constant, every year, is a blade logo that belongs to that Halloween and not to the standard mark. The 2024 page listed a sheet of themed logos: bats, a black cat, several jack-o'-lanterns, a skull, a spider, a web, and a witch carried over from 2018. You were assigned one based on the knife.",
            "The carved Halloween set also lives with the other series, on the [[Halloween series page|series/halloween/]].",
        ],
    )
    prose_page(
        "reviews/index.html",
        "about",
        "Other people's knives",
        "Reviews",
        "A few written reviews that have stuck to the line. Scores are theirs.",
        "Published reviews of Olamic knives.",
        [
            "Everyday Commentary, September 2016, on the Wayfarer 247. \"What an amazing knife. I was blown away the first time I fired it open.\" The written score was 19 out of 20. The summary line was \"Pure, solid awesomeness.\" [[The review|https://www.everydaycommentary.com/www.everydaycommentary.com//2016/09/olamic-cutlery-wayfarer-247-review.html]].",
            "Everyday Commentary, December 2017, on the Busker. 18 out of 20. \"Custom quality, production availability and design creativity. We have a winner.\" Design, fit, steel, and the lock were the high marks. [[The review|https://www.everydaycommentary.com/2017/12/18/olamic-busker-review]].",
            "BladeReviews, December 2018, on the 247. The knife they had was 8.125 inches overall, a 3.5 inch blade, 5 ounces, made in America. Their close: if you want a titanium flipper frame lock of that quality, and you want to make it yours, the 247 is an excellent choice. [[The review|https://bladereviews.com/olamic-wayfarer-247-review/]].",
            "Knife Informer on the Swish. Blade 3.75 inches, overall 8.62, weight 4.6 ounces on their scale, Elmax, frame lock, flipper, USA. They scored quality and performance at 83, value at 77, overall 80, and called it mid-tech done right. The clip and the lockbar were the complaints. [[The review|https://knifeinformer.com/olamic-swish-review/]].",
            "Video notes that match the shop's own history: early Wayfarer, Rainmaker, and Gambit customs had no CNC. From 2016, the parts that move were machined so the action would stay consistent, and the finish stayed in Visalia. Alexander Birykov is credited with the Rainmaker and the Swish. Serge Panchenko with the Gambit.",
        ],
    )
    prose_page(
        "fine-print/index.html",
        "support",
        "Policies",
        "Fine print",
        "What the old site said it collected, and where the warranty and returns actually live.",
        "Olamic privacy summary and pointers to the warranty.",
        [
            "The old fine-print page held a privacy policy, terms, a DMCA notice, a disclaimer, a cookie policy, and an acceptable use policy. The export of that page is long legal boilerplate. This page keeps the parts a buyer can use, in the shop's terms, and does not invent the clauses that were only headings here.",
            "Privacy, as published. You can read the site without identifying yourself. If you buy, write in, or fill a form, they store what you give them: name, country, email, address, and payment details when a payment is involved. Servers also log the usual technical data, IP address, browser, pages, and times, and they said that log is for abuse and for traffic counts, not for building a profile of you.",
            "They use the information to fill orders, deliver the knife, answer support, and run the site. Card data goes through a third-party processor, under that processor's policy. They said they do not share personal information with unaffiliated third parties for those parties' own marketing. They keep it as long as they need it for legal duties, disputes, and agreements.",
            "If you are in the EEA, the policy listed the usual rights: access, correction, deletion, restriction, and a copy of what they hold. The contact for that request is the shop, through [[support@olamiccutlery.com|mailto:support@olamiccutlery.com]].",
            "Returns and the warranty are spelled out on the [[warranty page|warranty/]], including the 72 hour window and the 25 percent and 10 percent restocking fees. Read that page before you send a knife back. It is the policy, not a summary of a different one.",
        ],
    )


def page_assistant() -> None:
    prefix = "../"
    models = []
    for model in MODELS:
        blades, steels, lock, opener = ASSIST[model["slug"]]
        models.append(
            {
                "name": model["name"],
                "blades": blades,
                "steels": steels,
                "lock": lock,
                "open": opener,
            }
        )
    payload = json.dumps({"models": models, "finishes": FINISHES})
    body = f"""
    <div class="wrap">
      {crumbs([("Home", ""), ("Build assistant", None)], prefix)}
      {head("Name the knife", "Build assistant", "The old assistant was a long catalog of finishes. This one is the short version: model, blade, steel, finish. It does not price anything and it does not order anything.", prefix)}
      <div class="assistant" id="assistant">
        <div class="form">
          <label>Model<select name="model"></select></label>
          <label>Blade<select name="blade"></select></label>
          <label>Steel<select name="steel"></select></label>
          <label>Finish<select name="finish"></select></label>
          <label>Anything else<textarea name="note" placeholder="Clip, backspacer, anodizing, a reference serial."></textarea></label>
          <button class="btn" type="button" data-request>Put this in the note</button>
        </div>
        <aside class="summary-card">
          <p class="kicker">This build</p>
          <div data-summary></div>
        </aside>
      </div>
      <form class="form" data-form style="margin-top:2rem">
        {form_fields('''
          <label>Topic<select name="topic"><option value="order">Build request</option></select></label>
          <label>The build<textarea id="build-message" name="message" required></textarea></label>
        ''', message=False)}
      </form>
      <script type="application/json" id="assistant-data">{payload}</script>
    </div>
    """
    write_page(
        "build-assistant/index.html",
        "Build assistant",
        "Pick a model, blade, steel, and finish. Nothing is ordered.",
        "knives",
        body,
    )


def page_404() -> None:
    body = """
    <div class="wrap">
      <header class="page-head">
        <p class="kicker">404</p>
        <h1>That page is not on this bench.</h1>
        <hr class="heat">
        <p class="lede"><a href="./">Back to the shop</a></p>
      </header>
    </div>
    """
    write_page("404.html", "Missing page", "That page is not on this Olamic preview.", "", body)


def main() -> None:
    print("images")
    attach_images()
    print("pages")
    page_home()
    page_models_index()
    for model in MODELS:
        page_model(model)
    page_series_index()
    for item in SERIES:
        page_series(item)
    page_news_index()
    for item in NEWS:
        page_news(item)
    page_simple_forms()
    page_assistant()
    page_404()
    print("done")


if __name__ == "__main__":
    main()

