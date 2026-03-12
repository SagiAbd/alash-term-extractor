#!/usr/bin/env python3
"""
Script to extract scientific terms from OCR results using Gemini API.
Reads ocr_results.json and outputs terms.xlsx.
"""

import json
import logging
import os
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from config import (
    TERMS_INPUT_FILE as INPUT_FILE,
    TERMS_OUTPUT_FILE as OUTPUT_FILE,
    TERMS_OVERLAP_CHARS as OVERLAP_CHARS,
    TERMS_MODEL_NAME as MODEL_NAME,
    CONST_YEAR,
    CONST_LINK,
    CONST_AUTHOR,
)
try:
    from config import CONST_TITLE
except ImportError:
    CONST_TITLE = ""

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)



def load_dotenv(env_path: Path = Path(".env")) -> None:
    """Load KEY=VALUE pairs from .env into process env without overwriting existing vars."""
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError as exc:
        log.warning("Could not read %s: %s", env_path, exc)


def configure_genai(api_key: str | None = None):
    """Configure the Gemini API. Uses the provided key, or falls back to GEMINI_API_KEY env var."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("API key required: pass --api-key or set GEMINI_API_KEY in .env")
    genai.configure(api_key=key)


def output_file_has_content(output_file: Path) -> bool:
    """Return True if output file exists and is non-empty."""
    if not output_file.exists():
        return False
    try:
        return output_file.stat().st_size > 0
    except OSError as exc:
        log.warning("Could not inspect %s: %s", output_file, exc)
        # Fail closed to avoid accidental overwrite of existing data.
        return True


def parse_page_num(page_data: Dict[str, Any]) -> int:
    """Parse page number from OCR entry; returns -1 if missing/invalid."""
    page_raw = page_data.get("page", -1)
    try:
        return int(page_raw)
    except (TypeError, ValueError):
        return -1

def load_ocr_results(filepath: Path) -> List[Dict[str, Any]]:
    """Load OCR results from JSON file."""
    if not filepath.exists():
        log.error("Input file not found: %s", filepath)
        return []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.error("Error decoding JSON file: %s", e)
        return []

def create_extraction_prompt(text: str, prev_tail: str = "", next_head: str = "") -> str:
    """Create the prompt for term extraction."""
    context_block = ""
    if prev_tail:
        context_block += f"\n[АЛДЫҢҒЫ БЕТ СОҢЫ — тек контекст үшін]:\n\"\"\"\n{prev_tail}\n\"\"\"\n"
    context_block += f"\n[НЕГІЗГІ МЕТін — осы беттен ғана терминдер алыңыз]:\n\"\"\"\n{text}\n\"\"\""
    if next_head:
        context_block += f"\n\n[КЕЛЕСІ БЕТ БАСЫ — тек контекст үшін]:\n\"\"\"\n{next_head}\n\"\"\"\n"

    return f"""
Сіз Алаш кезеңінің (ХХ ғасырдың басы) тіл білімі мен ғылым тарихы бойынша сарапшысыз.
Сіз Алаш кезеңіне жататын ғылыми немесе оқу мәтінін (тарихи мәтін) талдап жатырсыз.

Сіздің мақсатыңыз: Мәтіннен **кез келген пәнге жататын** арнайы терминдерді, ғылыми ұғымдарды, техникалық сөздерді, өлшем бірліктерін, кәсіби атауларды теріп алу.

Талданатын мәтін:
{context_block}

МАҢЫЗДЫ: Терминдерді тек **НЕГІЗГІ МӘТІННЕН** алыңыз. Алдыңғы/келесі бет мәтіндері тек анықтаманың бет шегінде үзілмеуін тексеру үшін берілген.

### НЕГІЗГІ ЕРЕЖЕЛЕР (ҚАТАҢ САҚТАЛСЫН):

1. **Тақырып ауқымы — КЕҢ ПӘНАРАЛЫҚ**:
   Мәтін **кез келген пәнге** — физика, химия, биология, математика, медицина, заң, тарих, экономика, философия, география, техника және т.б. — жататын болуы мүмкін. Пәнге қарамастан **барлық арнайы, кәсіби немесе ғылыми терминдерді** алыңыз.

2. **ТЕРМИНДІ ҚАЛАЙ ТАНУҒА БОЛАДЫ?**
   Термин дегеніміз — жалпы тұрмыстық сөз емес, белгілі бір пән немесе кәсіп аясында **арнайы мағынасы бар** сөз немесе сөз тіркесі.
   - **Алыңыз**: "күш", "салмақ", "буын", "тамыр жүйесі", "балық сүйегі", "жылдамдық", "тепе-теңдік", "айналым капиталы", "сот талқылауы", "заңды тұлға".
   - **АЛМАҢЫЗ**: "кітап", "адам", "бару", "үлкен", "бет" — бұлар жалпы қолданыстағы сөздер.
   - **КҮМӘН ТУСА**: егер сөз жалпы халыққа таныс болмаса немесе белгілі бір пән аясында ерекше мағынасы болса — оны **алыңыз**.

3. **АНЫҚТАМАСЫ БАР НЕМЕСЕ ЖОҚ — ЕКЕУІН ДЕ АЛЫҢЫЗ**:
   - Егер мәтінде термин **анықталса немесе түсіндірілсе** → `is_definition: true`, `alash_definition` өрісіне сол анықтаманы **ТҮПНҰСҚАДАН ӨЗГЕРІССІЗ** көшіріп жазыңыз.
   - Егер термин **жай ғана қолданылған, бірақ түсіндірілмеген** болса → `is_definition: false`, `alash_definition` өрісін **БОС** қалдырыңыз.

4. **Сүзгілеу (Алуға БОЛМАЙДЫ)**:
   - Жалпы қолданыстағы сөздерді ("кітап", "бет", "білу", "адам", "үй", "жер").
   - Жалпы етістіктерді (егер ол арнайы ғылыми процесс немесе операция болмаса).
   - Жалқы есімдерді (адам аттары, жер аттары).
   - Мағынасыз сөз үзінділерін немесе жеке тұрған сандарды.

5. **Терминге не жатады (мысалдар)**:
   - Ғылыми шамалар мен ұғымдар (физика, химия, математика...).
   - Биологиялық, медициналық атаулар ("балық сүйегі", "буын", "тамыр").
   - Заңдық терминдер ("сот", "мүлік", "шарт", "айып").
   - Экономикалық атаулар ("салық", "капитал", "баға").
   - Философиялық ұғымдар ("болмыс", "таным", "сана").
   - Педагогикалық және қазақ тіліне қатысты терминдер ("дыбыс", "буын", "сөйлем мүшесі", "әліппе", "оқыту әдісі", "тәрбие").
   - Өлшем бірліктер, Құрал-жабдықтар.
   - Арнайы кәсіби атаулар (кез келген пән бойынша).
   - Мәтінде **қалың қаріппен (bold)** берілген сөздер/сөз тіркестері термин болуы мүмкін; оларды да міндетті түрде тексеріп, сәйкес келсе термин ретінде алыңыз.

### ШЫҒАРЫЛАТЫН МӘЛІМЕТТЕР (ӨТЕ МАҢЫЗДЫ):

Төмендегі өрістер бойынша JSON қайтарыңыз.

1. **alash_term** (Алаш термині): Мәтінде қалай жазылса, **ДӘЛ СОЛАЙ, ӨЗГЕРІССІЗ** алынсын. Ешқандай түзету енгізбеңіз.
2. **modern_term** (Заманауи термин): Осы терминнің қазіргі қазақ тіліндегі ғылыми баламасы.
3. **field** (Сала): Ғылым саласы (Физика, Химия, Биология, Математика, Медицина, Заң, Экономика, Философия, Тарих, Техника және т.б.).
4. **subfield** (Кіші сала): Нақты бөлімі (мысалы: Механика, Оптика, Тұқым қуалаушылық, Азаматтық заң т.б.).
5. **modern_definition** (Заманауи түсініктеме): Терминнің қазіргі ғылыми анықтамасы (МІНДЕТТІ, is_definition мәніне қарамастан).
6. **alash_definition** (Алаш түсініктемесі): Егер `is_definition: true` болса — автор берген анықтама сөйлемін мәтіннен **ДӘЛМЕ-ДӘЛ КӨШІРІҢІЗ**. Егер `is_definition: false` болса — **БОС ЖОЛДЫ** қалдырыңыз ("").
7. **is_definition** (Анықтама бар ма?): `true` — егер мәтінде терминнің анықтамасы/түсіндірмесі берілген болса; `false` — егер термин тек қолданылған, бірақ анықталмаған болса.
8. **context** (Контекст): Термин кездесетін сөйлем және оның айналасындағы 1-2 сөйлем (контекст үшін). Мәтіннен **ДӘЛМЕ-ДӘЛ КӨШІРІЛСІН (COPY-PASTE)**. Түзетуге, қысқартуға болмайды.
9. **significance** (Ғылыми маңызы): Бұл термин ғылыми тіл қалыптастыруда несімен маңызды?

### OUTPUT FORMAT (JSON ONLY):
Return ONLY a valid JSON object. Keys must be in English for JSON structure, values in Kazakh.
{{
  "terms": [
    {{
      "alash_term": "...",
      "modern_term": "...",
      "field": "...",
      "subfield": "...",
      "modern_definition": "...",
      "alash_definition": "...",
      "is_definition": true,
      "context": "...",
      "significance": "..."
    }}
  ]
}}
"""

def extract_terms_from_page(
    page_data: Dict[str, Any],
    model,
    prev_text: str = "",
    next_text: str = "",
) -> List[Dict[str, Any]]:
    """Extract terms from a single page using Gemini API."""
    page_num = page_data.get("page", -1)
    text = page_data.get("text", "")

    if not text.strip():
        log.warning("Page %d has no text, skipping.", page_num)
        return []

    prev_tail = prev_text[-OVERLAP_CHARS:] if prev_text else ""
    next_head = next_text[:OVERLAP_CHARS] if next_text else ""
    prompt = create_extraction_prompt(text, prev_tail=prev_tail, next_head=next_head)

    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
            safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )

        try:
            result = json.loads(response.text)
            terms = result.get("terms", [])

            # Enrich extracted terms with metadata
            enriched_terms = []
            for term in terms:
                enriched_terms.append({
                    "Заманауи термин": term.get("modern_term", ""),
                    "Алаш термині": term.get("alash_term", ""),
                    "Сала": term.get("field", ""),
                    "Кіші сала(subfield)": term.get("subfield", ""),
                    "Заманауи түсініктеме": term.get("modern_definition", ""),
                    "Алаш түсініктемесі": term.get("alash_definition", ""),
                    "Анықтама бар ма": term.get("is_definition", False),
                    "Екі бет арасындағы мәтін -- контекст үшін": term.get("context", ""),
                    "Авторы": CONST_AUTHOR,
                    "Басталатын беті": page_num,
                    "Аяқталу беті": page_num,
                    "Жазылу жылы": CONST_YEAR,
                    "Сілтеме": CONST_LINK,
                    "Ғылыми дискурсқа маңызы": term.get("significance", "")
                })

            log.info("Page %d: Extracted %d terms.", page_num, len(enriched_terms))
            return enriched_terms

        except json.JSONDecodeError:
            log.error("Page %d: Failed to parse JSON response.", page_num)
            return []

    except Exception as e:
        log.error("Page %d: API error: %s", page_num, e)
        if "429" in str(e):
            log.warning("Rate limit hit, waiting 60s...")
            time.sleep(60)
            return extract_terms_from_page(page_data, model, prev_text, next_text)  # Retry once
        return []


def deduplicate_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate terms by alash_term, keeping the entry with the longest alash_definition."""
    seen: Dict[str, Dict[str, Any]] = {}
    for term in terms:
        key = term.get("Алаш термині", "").strip().lower()
        if not key:
            continue
        existing = seen.get(key)
        if existing is None or len(term.get("Алаш түсініктемесі", "")) > len(existing.get("Алаш түсініктемесі", "")):
            seen[key] = term
    result = list(seen.values())
    removed = len(terms) - len(result)
    if removed:
        log.info("Deduplication: removed %d duplicate term(s), %d unique term(s) remain.", removed, len(result))
    return result

def main():
    parser = argparse.ArgumentParser(description="Extract terms from OCR results to Excel")
    parser.add_argument("--limit", type=int, help="Limit number of pages to process (for testing, index-based mode)")
    parser.add_argument("--start", type=int, default=0, help="Start page index (0-based, index-based mode)")
    parser.add_argument("--start-page", "-s", type=int, default=None, help="Start page number (inclusive)")
    parser.add_argument("--end-page", "-e", type=int, default=None, help="End page number (inclusive)")
    parser.add_argument("--api-key", type=str, default=None, help="Gemini API key (overrides GEMINI_API_KEY env var)")
    args = parser.parse_args()

    load_dotenv()

    if args.start < 0:
        parser.error("--start must be >= 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.start_page is not None and args.start_page < 1:
        parser.error("--start-page must be >= 1")
    if args.end_page is not None and args.end_page < 1:
        parser.error("--end-page must be >= 1")
    if (
        args.start_page is not None
        and args.end_page is not None
        and args.start_page > args.end_page
    ):
        parser.error("--start-page cannot be greater than --end-page")
    if (
        (args.start_page is not None or args.end_page is not None)
        and (args.start != 0 or args.limit is not None)
    ):
        parser.error("Use either --start/--limit (index mode) or --start-page/--end-page (page mode), not both")
    if output_file_has_content(Path(OUTPUT_FILE)):
        log.error(
            "Output file is not empty: %s\n"
            "Stop to prevent overriding/mixing old files. Please back up or clear this file, then rerun.",
            Path(OUTPUT_FILE).resolve(),
        )
        return

    configure_genai(args.api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    
    ocr_data = load_ocr_results(Path(INPUT_FILE))
    if not ocr_data:
        log.error("No OCR data loaded.")
        return

    selected_indices: List[int] = []
    if args.start_page is not None or args.end_page is not None:
        skipped_invalid = 0
        for i, page_data in enumerate(ocr_data):
            page_num = parse_page_num(page_data)
            if page_num < 1:
                skipped_invalid += 1
                continue
            if args.start_page is not None and page_num < args.start_page:
                continue
            if args.end_page is not None and page_num > args.end_page:
                continue
            selected_indices.append(i)
        if skipped_invalid:
            log.warning("Skipped %d OCR record(s) with invalid page numbers.", skipped_invalid)
        if not selected_indices:
            log.warning(
                "No OCR records matched page range %s-%s.",
                args.start_page if args.start_page is not None else "*",
                args.end_page if args.end_page is not None else "*",
            )
            return
        log.info(
            "Processing %d OCR record(s) in page range %s-%s.",
            len(selected_indices),
            args.start_page if args.start_page is not None else "*",
            args.end_page if args.end_page is not None else "*",
        )
    else:
        start_idx = args.start
        end_idx = start_idx + args.limit if args.limit else len(ocr_data)
        if start_idx >= len(ocr_data):
            log.warning(
                "Start index %d is out of range for OCR dataset of size %d.",
                start_idx,
                len(ocr_data),
            )
            return
        end_idx = min(end_idx, len(ocr_data))
        selected_indices = list(range(start_idx, end_idx))
        log.info("Processing OCR indices %d to %d.", start_idx, end_idx - 1)

    all_terms = []

    for processed_count, src_idx in enumerate(selected_indices, start=1):
        page = ocr_data[src_idx]
        prev_text = ocr_data[src_idx - 1].get("text", "") if src_idx > 0 else ""
        next_text = ocr_data[src_idx + 1].get("text", "") if src_idx < len(ocr_data) - 1 else ""
        terms = extract_terms_from_page(page, model, prev_text=prev_text, next_text=next_text)
        all_terms.extend(terms)
        # Sleep to avoid hitting rate limits too hard
        time.sleep(2)
        if processed_count % 10 == 0:
            log.info("Processed %d page(s)...", processed_count)

    all_terms = deduplicate_terms(all_terms)

    if not all_terms:
        log.warning("No terms extracted.")
        return

    # Create DataFrame
    df = pd.DataFrame(all_terms)

    # Ensure column order
    columns = [
        "Заманауи термин", "Алаш термині", "Сала", "Кіші сала(subfield)",
        "Заманауи түсініктеме", "Алаш түсініктемесі", "Анықтама бар ма",
        "Екі бет арасындағы мәтін -- контекст үшін", "Авторы",
        "Басталатын беті", "Аяқталу беті", "Жазылу жылы", "Сілтеме",
        "Ғылыми дискурсқа маңызы"
    ]
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns]

    # Save to Excel with metadata header block
    try:
        _save_with_metadata_header(df, OUTPUT_FILE)
        log.info("Successfully saved %d terms to %s", len(df), OUTPUT_FILE)
    except Exception as e:
        log.error("Failed to save Excel file: %s", e)


def _save_with_metadata_header(df: pd.DataFrame, output_path: str):
    """
    Write *df* to an Excel file, preceded by a styled metadata block.
    Metadata rows are bold, font size 24. Labels are in Kazakh.

    Layout:
      Row 1  : Кітап атауы  | <title>
      Row 2  : Авторы        | <author>
      Row 3  : Жазылу жылы  | <year>
      Row 4  : Сілтеме      | <link>
      Row 5  : (blank)
      Row 6  : column headers (bold, size 11)
      Row 7+ : data
    """
    meta_rows = [
        ("Кітап атауы",  CONST_TITLE  or ""),
        ("Авторы",       CONST_AUTHOR or ""),
        ("Жазылу жылы",  str(CONST_YEAR) if CONST_YEAR else ""),
        ("Сілтеме",      CONST_LINK   or ""),
    ]

    meta_font   = Font(bold=True, size=24)
    header_font = Font(bold=True, size=11)

    wb = openpyxl.Workbook()
    ws = wb.active

    # --- Metadata rows ---
    for i, (label, value) in enumerate(meta_rows, start=1):
        lc = ws.cell(row=i, column=1, value=label)
        vc = ws.cell(row=i, column=2, value=value)
        lc.font = meta_font
        vc.font = meta_font
        ws.row_dimensions[i].height = 36  # tall enough for 24pt font

    # Blank separator row (row 5 when 4 meta rows)
    blank_row  = len(meta_rows) + 1
    header_row = blank_row + 1

    # --- Column header row ---
    for col_idx, col_name in enumerate(df.columns, start=1):
        hc = ws.cell(row=header_row, column=col_idx, value=col_name)
        hc.font = header_font

    # --- Data rows ---
    for r_idx, row in enumerate(df.itertuples(index=False), start=header_row + 1):
        for c_idx, value in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=value)

    wb.save(output_path)


if __name__ == "__main__":
    main()
