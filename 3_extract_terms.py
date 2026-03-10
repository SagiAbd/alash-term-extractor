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
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Constants
INPUT_FILE = "ocr_results.json"
OUTPUT_FILE = "terms.xlsx"
OVERLAP_CHARS = 300  # Characters from adjacent pages to include as context
MODEL_NAME = "gemini-2.5-flash"

# Metadata constants requested by user
CONST_YEAR = 1923
CONST_LINK = "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true#"
CONST_AUTHOR = "Е.Омарұлы - Физика"

def configure_genai(api_key: str | None = None):
    """Configure the Gemini API. Uses the provided key, or falls back to GEMINI_API_KEY env var."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("API key required: pass --api-key or set GEMINI_API_KEY in .env")
    genai.configure(api_key=key)

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
   - Өлшем бірліктер, Құрал-жабдықтар.
   - Арнайы кәсіби атаулар (кез келген пән бойынша).

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
    parser.add_argument("--limit", type=int, help="Limit number of pages to process (for testing)")
    parser.add_argument("--start", type=int, default=0, help="Start page index (0-based)")
    parser.add_argument("--api-key", type=str, default=None, help="Gemini API key (overrides GEMINI_API_KEY env var)")
    args = parser.parse_args()

    configure_genai(args.api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    
    ocr_data = load_ocr_results(Path(INPUT_FILE))
    if not ocr_data:
        log.error("No OCR data loaded.")
        return

    start_idx = args.start
    end_idx = start_idx + args.limit if args.limit else len(ocr_data)
    
    ocr_data = ocr_data[start_idx:end_idx]
    log.info("Processing pages %d to %d.", start_idx + 1, end_idx)

    all_terms = []

    for i, page in enumerate(ocr_data):
        prev_text = ocr_data[i - 1].get("text", "") if i > 0 else ""
        next_text = ocr_data[i + 1].get("text", "") if i < len(ocr_data) - 1 else ""
        terms = extract_terms_from_page(page, model, prev_text=prev_text, next_text=next_text)
        all_terms.extend(terms)
        # Sleep to avoid hitting rate limits too hard
        time.sleep(2)
        if (i + 1) % 10 == 0:
            log.info("Processed %d pages...", i + 1)

    all_terms = deduplicate_terms(all_terms)

    if not all_terms:
        log.warning("No terms extracted.")
        return

    # Create DataFrame
    df = pd.DataFrame(all_terms)
    
    # Ensure column order matches user request
    columns = [
        "Заманауи термин", "Алаш термині", "Сала", "Кіші сала(subfield)",
        "Заманауи түсініктеме", "Алаш түсініктемесі", "Анықтама бар ма",
        "Екі бет арасындағы мәтін -- контекст үшін", "Авторы",
        "Басталатын беті", "Аяқталу беті", "Жазылу жылы", "Сілтеме",
        "Ғылыми дискурсқа маңызы"
    ]
    
    # Reorder columns if they exist, create if missing (though they should be there)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
            
    # Select only required columns and in the correct order
    df = df[columns]

    # Save to Excel
    try:
        df.to_excel(OUTPUT_FILE, index=False)
        log.info("Successfully saved %d terms to %s", len(df), OUTPUT_FILE)
    except Exception as e:
        log.error("Failed to save Excel file: %s", e)

if __name__ == "__main__":
    main()
