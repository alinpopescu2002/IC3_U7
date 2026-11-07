"""
Completez sablonul de 3 slide-uri pentru CP2 cu rezultatele din 06_baselines.py.
Rulare: python src/07_make_slides_cp2.py   ->  CP2_U7.pptx
"""
import json
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
NAVY, CREAM, WHITE = RGBColor(0x1B, 0x2A, 0x41), RGBColor(0xF6, 0xF4, 0xEE), RGBColor(0xFF, 0xFF, 0xFF)
ORANGE, INK, HILITE = RGBColor(0xC8, 0x70, 0x2A), RGBColor(0x1B, 0x2A, 0x41), RGBColor(0xF3, 0xDF, 0xC8)
FONT = "IBM Plex Sans"


def set_text(shape, text, size=None):
    tf = shape.text_frame
    runs = tf.paragraphs[0].runs
    old = runs[0].font.size
    runs[0].text = text
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.word_wrap = True
    runs[0].font.size = Pt(size) if size else (old or Pt(14))
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)


def by_name(slide, name):
    return next(s for s in slide.shapes if s.name == name)


def place(slide, name, top, height):
    sh = by_name(slide, name)
    sh.top, sh.height = Inches(top), Inches(height)


def add_table(slide, rows, x, y, widths, row_h, size=9, highlight=None):
    shp = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y),
                                 Inches(sum(widths)), Inches(row_h * len(rows)))
    tbl = shp.table
    for j, w in enumerate(widths):
        tbl.columns[j].width = Inches(w)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            c = tbl.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.06)
            c.margin_top = c.margin_bottom = Inches(0.03)
            c.fill.solid()
            c.fill.fore_color.rgb = NAVY if i == 0 else (HILITE if i == highlight else (WHITE if i % 2 else CREAM))
            p = c.text_frame.paragraphs[0]
            c.text_frame.word_wrap = True
            p.text = ""
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            r.font.size, r.font.name = Pt(size), FONT
            r.font.bold = (i == 0) or (j == 0) or (i == highlight)
            r.font.color.rgb = WHITE if i == 0 else INK
    return shp


def label(slide, text, x, y, w, size=10, color=ORANGE, bold=True):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.3))
    tf = tb.text_frame
    tf.auto_size, tf.word_wrap = MSO_AUTO_SIZE.NONE, True
    tf.margin_left = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = text
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, FONT
    r.font.color.rgb = color
    return tb


def fmt(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def main():
    s = pd.read_csv(PROC / "baseline_summary.csv")
    info = json.loads((PROC / "baseline_info.json").read_text(encoding="utf-8"))
    targets = [t for t in ("pm10", "pm25") if t in set(s.target)]
    methods = list(dict.fromkeys(s[s.target == targets[0]].method))
    has_b = any("AlphaEarth" in m for m in methods)

    def get(t, prot, m, col):
        r = s[(s.target == t) & (s.protocol == prot) & (s.method == m)]
        return float(r[col].iloc[0]) if len(r) else float("nan")

    # tinta principala: PM10 (62 statii); PM2.5 are prea putine statii pentru concluzii ferme
    t0 = "pm10" if "pm10" in targets else targets[0]
    tname = {"pm25": "PM2.5", "pm10": "PM10"}
    sp = s[(s.target == t0) & (s.protocol == "spațial")].set_index("method")
    best = sp.rmse.idxmin()
    best_rmse = sp.loc[best, "rmse"]
    simple = sp[~sp.index.str.startswith("RF")]
    simple_rmse = simple.rmse.min()
    # baseline-urile simple la egalitate (diferenta < 1%) le numesc impreuna
    simple_best = [m.split(" (")[0] for m in simple.index if simple.loc[m, "rmse"] <= simple_rmse * 1.01]
    simple_name = " / ".join(simple_best)
    rfa = next(m for m in methods if m.startswith("RF (A"))
    rf_sp, rf_rnd = get(t0, "spațial", rfa, "rmse"), get(t0, "aleator", rfa, "rmse")
    optim = 100 * (rf_sp - rf_rnd) / rf_sp
    n_txt = " și ".join(f"{info[t]['n_stations']} stații {tname[t]}" for t in ("pm10", "pm25") if t in info)

    prs = Presentation(ROOT / "docs" / "template_IC3.pptx")
    s1, s2, s3 = prs.slides

    # ---------- Slide 1 ----------
    set_text(by_name(s1, "Text 0"), "IC3 · CP2 · REPREZENTARE · SĂPTĂMÂNA 6")
    set_text(by_name(s1, "Text 1"), "Popescu Alin · U7 · UrbanTwin: rețeaua de senzori de aer")
    set_text(by_name(s1, "Text 4"), "Cum estimăm câmpul continuu de PM2.5/PM10 în punctele neobservate din "
                                    "București, ca să alegem locul următorului senzor de aer?")
    set_text(by_name(s1, "Text 6"), "Urbanism, Primăria București → unde se instalează următorul senzor fizic")
    set_text(by_name(s1, "Text 9"), "Strat curent: reprezentare")
    set_text(by_name(s1, "Text 10"),
             "Făcut: reprezentarea stație-zi (coordonate, LST, calendar, vecini) + alternativa AlphaEarth; "
             f"4 baseline-uri rulate pe {n_txt}, 5 fold-uri spațiale")
    set_text(by_name(s1, "Text 11"),
             "Schimbat: persistența nu se aplică într-un punct fără senzor → înlocuită cu media orașului "
             "din aceeași zi; LOYO amânat (doar anul 2024)")
    set_text(by_name(s1, "Text 12"), "Slide 1 din 3 · Fișier Moodle: CP2_U7.pdf · Prezentare: 3 minute")
    by_name(s1, "Text 4").height = Inches(1.1)
    place(s1, "Text 5", 3.75, 0.4)
    place(s1, "Text 6", 4.12, 0.9)
    place(s1, "Text 10", 3.05, 0.95)
    place(s1, "Text 11", 4.15, 0.95)

    # ---------- Slide 2 ----------
    if rf_sp > simple_rmse:
        title = (f"În stații ascunse, RF ({fmt(rf_sp)}) nu bate {simple_name} ({fmt(simple_rmse)} µg/m³ "
                 f"{tname[t0]}); cu split aleator, RF ar părea cu {fmt(abs(optim), 0)}% mai bun")
    else:
        gain = 100 * (simple_rmse - rf_sp) / simple_rmse
        title = (f"În stații ascunse, RF are RMSE {fmt(rf_sp)} µg/m³ {tname[t0]} (−{fmt(gain, 0)}% față de "
                 f"{simple_name}); cu split aleator ar părea cu {fmt(abs(optim), 0)}% mai bun")
    set_text(by_name(s2, "Text 1"), title, size=26)
    for n in ("Text 3", "Text 4"):
        el = by_name(s2, n)._element
        el.getparent().remove(el)
    x0, y0 = 1.02, 2.4
    label(s2, "BASELINE-URI: RMSE (µg/m³) PE STAȚII ASCUNSE, MEDIE ± ABATERE PE 5 FOLD-URI", x0, y0, 7.2)
    head = ["Metodă"]
    for t in targets:
        head += [f"{tname[t]} spațial", f"R²", "aleator"]
    rows = [head]
    for m in methods:
        r = [m]
        for t in targets:
            r += [f"{fmt(get(t, 'spațial', m, 'rmse'))} ± {fmt(get(t, 'spațial', m, 'rmse_sd'))}",
                  fmt(get(t, "spațial", m, "r2"), 2),
                  fmt(get(t, "aleator", m, "rmse"))]
        rows.append(r)
    widths = [2.15] + [1.05, 0.55, 0.75] * len(targets)
    hl = methods.index(best) + 1
    add_table(s2, rows, x0, y0 + 0.3, widths, 0.44, size=10, highlight=hl)
    ny = y0 + 0.3 + 0.44 * len(rows) + 0.15
    label(s2, "Persistența (mâine = azi) nu e posibilă: în punctul fără senzor nu există „azi”. "
              "Coloana „aleator” = aceleași modele cu split pe rânduri stație-zi (leakage), "
              f"pentru RF cu {fmt(abs(optim), 0)}% mai optimist.", x0, ny, 7.2, size=10, color=INK, bold=False)

    set_text(by_name(s2, "Text 7"), "Repo: github.com/alinpopescu2002/IC3_U7", size=11)
    set_text(by_name(s2, "Text 8"), "Reprezentare A: coordonate, LST lunar, zi din an, vecinii din aceeași zi "
                                    "(IDW, medie, distanța la cel mai apropiat)"
             + (" · B: AlphaEarth 64-d + vecini" if has_b else " · B: AlphaEarth 64-d (script 05)"), size=11)
    set_text(by_name(s2, "Text 9"), "Split: spațial, 5 fold-uri de stații. Testul imită exact un punct fără senzor",
             size=11)
    set_text(by_name(s2, "Text 10"), "Cod: 06_baselines.py · seed 42 · RF 300", size=11)
    note = ""
    if t0 != "pm25" and "pm25" in targets:
        note = (f" (PM2.5: ~{fmt(get('pm25', 'spațial', best, 'rmse'), 0)}, dar doar "
                f"{info['pm25']['n_stations']} stații și R² ≈ 0)")
    set_text(by_name(s2, "Text 11"), "Pentru client: eroarea tipică într-un punct fără senzor e "
                                     f"~{fmt(best_rmse, 0)} µg/m³ {tname[t0]}{note}. Asta e ținta de bătut la CP3.",
             size=11)
    for n, top, h in (("Text 7", 2.85, 0.35), ("Text 8", 3.25, 1.05), ("Text 9", 4.2, 0.6),
                      ("Text 10", 4.9, 0.35), ("Text 11", 5.45, 0.85)):
        place(s2, n, top, h)
    set_text(by_name(s2, "Text 12"), "Slide 2 din 3 · Rezultate per fold: data/processed/baseline_results_per_fold.csv")

    # ---------- Slide 3 ----------
    set_text(by_name(s3, "Text 0"), "BLOCAJE ȘI URMĂTOARELE DOUĂ SĂPTĂMÂNI")
    set_text(by_name(s3, "Text 1"), "Blocaje și următorii pași la CP3")
    b_txt = ("1. AlphaEarth e anual (static) → descrie bine locul, dar nu ziua; "
             "ajută doar prin diferențele dintre cartiere") if has_b else \
        "1. Embeddings AlphaEarth încă neextrase (scriptul 05 e gata) → comparația A vs B la CP3"
    set_text(by_name(s3, "Text 4"), b_txt)
    set_text(by_name(s3, "Text 5"), "2. Un singur an de date → LOYO imposibil acum; descarc 2023 pentru CP4")
    set_text(by_name(s3, "Text 6"), "Riscul la CP3: puține stații la periferie → erori mari exact unde "
                                    "decide clientul; raportez eroarea și pe distanța la cea mai apropiată stație")
    place(s3, "Text 4", 2.6, 0.9)
    place(s3, "Text 5", 3.6, 0.7)
    place(s3, "Text 6", 4.4, 1.0)
    set_text(by_name(s3, "Text 9"), "Săptămâna 7: metoda de CI: Gaussian Process (kernel spațial + LST/AlphaEarth), "
                                    "care dă și incertitudine în fiecare punct")
    set_text(by_name(s3, "Text 10"), "Săptămâna 8: GP vs. RF vs. IDW pe aceleași 5 fold-uri spațiale × 3 seed-uri")
    set_text(by_name(s3, "Text 11"), "La CP3 arăt: model vs. baseline cu intervale de încredere")
    set_text(by_name(s3, "Text 12"), "Secțiunea de articol: Methods (model) + începutul Results")
    for n, top, h in (("Text 9", 2.43, 0.9), ("Text 10", 3.4, 0.7), ("Text 11", 4.15, 0.6), ("Text 12", 4.85, 0.6)):
        place(s3, n, top, h)
    set_text(by_name(s3, "Text 13"), "Slide 3 din 3 · Întrebare: e acceptat media orașului din aceeași zi "
                                     "ca înlocuitor al persistenței?")

    out = ROOT / "CP2_U7.pptx"
    prs.save(out)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
