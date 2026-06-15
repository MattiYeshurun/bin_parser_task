"""
app.py -- נקודת כניסה ראשית לעיבוד קובצי BIN
===============================================

מספק ממשק שורת פקודה (CLI) נקי עם שלוש אפשרויות:
  1. תיאור מבנה הקובץ (FMT definitions, message counts)
  2. קריאה והצגה של הודעות GPS
  3. הרצת benchmark מלא בין כל שיטות הקריאה

שימוש:
    python app.py                  # מריץ הכל (תיאור + GPS + benchmark)
    python app.py --describe       # רק תיאור מבנה הקובץ
    python app.py --gps            # רק הודעות GPS
    python app.py --benchmark      # רק benchmark
    python app.py --runs 5         # benchmark עם 5 ריצות לכל שיטה
    python app.py --workers 4      # benchmark עם 4 workers
    python app.py myfile.bin       # שימוש בקובץ אחר

פלט צפוי (python app.py):
    שלב 1: טבלת 175 סוגי הודעות + ספירה (7.4M סה"כ)
    שלב 2: 20 הודעות GPS ראשונות + סטטיסטיקות
    שלב 3: טבלת benchmark של 5 שיטות עם speedup
"""

# ייבוא annotations לתמיכה בטיפוסים מתקדמים
from __future__ import annotations

# argparse -- ספרייה לפירוש ארגומנטים משורת הפקודה
# מאפשרת להגדיר --describe, --gps, --benchmark וכו'
import argparse

# sys -- לגישה לפרמטרי מערכת (sys.exit לסיום עם קוד שגיאה)
import sys

# Path -- ממשק נוח לעבודה עם נתיבי קבצים
from pathlib import Path


def main() -> None:
    """
    הפונקציה הראשית -- מפרסרת ארגומנטים ומפעילה את השלבים המבוקשים.
    """

    # --- הגדרת ארגומנטי שורת הפקודה ---

    # יוצרים parser של ארגומנטים עם תיאור כללי
    parser = argparse.ArgumentParser(
        description='ArduPilot BIN File Parser & Benchmark Tool'
    )

    # ארגומנט מיקום (positional) -- נתיב לקובץ BIN
    # nargs='?' = אופציונלי (אם לא ניתן, משתמשים בברירת מחדל)
    parser.add_argument(
        'file', nargs='?', default='log_file_test_01.bin',
        help='Path to the BIN log file (default: log_file_test_01.bin)'
    )

    # --describe -- דגל להצגת מבנה הקובץ
    # action='store_true' = אם הדגל קיים, הערך הוא True
    parser.add_argument(
        '--describe', action='store_true',
        help='Show file structure and message type summary'
    )

    # --gps -- דגל להצגת הודעות GPS
    parser.add_argument(
        '--gps', action='store_true',
        help='Show GPS messages'
    )

    # --benchmark -- דגל להרצת benchmark
    parser.add_argument(
        '--benchmark', action='store_true',
        help='Run the full benchmark comparison'
    )

    # --runs -- מספר ריצות benchmark (ברירת מחדל: 3)
    parser.add_argument(
        '--runs', type=int, default=3,
        help='Number of benchmark runs per method (default: 3)'
    )

    # --workers -- מספר workers (ברירת מחדל: אוטומטי לפי מספר ליבות)
    parser.add_argument(
        '--workers', type=int, default=None,
        help='Number of parallel workers (default: auto-detect CPU count)'
    )

    # מפרסרים את הארגומנטים שהמשתמש הזין
    args = parser.parse_args()

    # ממירים את נתיב הקובץ לאובייקט Path
    file_path = Path(args.file)

    # בודקים שהקובץ קיים -- אם לא, מדפיסים שגיאה ויוצאים
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)  # קוד יציאה 1 = שגיאה

    # אם לא ניתן שום דגל ספציפי -- מריצים את הכל
    run_all = not (args.describe or args.gps or args.benchmark)

    # =====================================================================
    # שלב 1: תיאור מבנה הקובץ
    # מציג את כל 175 סוגי ההודעות שמוגדרים בקובץ,
    # כולל שם, פורמט, שדות, וספירה של כל סוג.
    # =====================================================================
    if args.describe or run_all:
        # ייבוא מאוחר -- רק אם נדרש (חוסך זמן טעינה)
        from bin_parser_task.bin_parser import BinParser

        print(f"\n{'=' * 80}")
        print(f"  STEP 1 -- File Structure Analysis")
        print(f"{'=' * 80}\n")

        # יוצרים פרסר -- קורא את FMTs אוטומטית
        bp = BinParser(file_path)

        # מדפיסים טבלה של כל סוגי ההודעות
        bp.describe()

        # סופרים כמה הודעות מכל סוג ומדפיסים ממוין לפי כמות
        print(f"\n--- Message Type Counts ---\n")
        counts = bp.get_message_type_summary()
        total = 0
        for name, count in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {name:<8} {count:>8,}")  # שם מיושר שמאלה, מספר מיושר ימינה
            total += count
        print(f"  {'TOTAL':<8} {total:>8,}")  # שורת סיכום

    # =====================================================================
    # שלב 2: קריאת הודעות GPS
    # מדגים קריאת סוג הודעה ספציפי -- מציג את ההודעות הראשונות
    # עם קואורדינטות lat/lng מפוענחות וסטטיסטיקות.
    # =====================================================================
    if args.gps or run_all:
        # ייבוא מאוחר מתוך bin_parser.py
        from bin_parser_task.bin_parser import print_gps_summary

        print(f"\n{'=' * 80}")
        print(f"  STEP 2 -- GPS Message Reading")
        print(f"{'=' * 80}\n")

        # מדפיסים 15 הודעות GPS ראשונות + סטטיסטיקות
        print_gps_summary(file_path, max_display=15)

    # =====================================================================
    # שלב 3: השוואת ביצועים (benchmark)
    # מריץ את כל 5 שיטות הקריאה ומציג טבלת השוואה
    # עם זמנים, קצבים, ו-speedup ביחס לשיטה הסדרתית.
    # =====================================================================
    if args.benchmark or run_all:
        # ייבוא מאוחר מתוך bin_parser.py
        from bin_parser_task.bin_parser import run_full_benchmark

        print(f"\n{'=' * 80}")
        print(f"  STEP 3 -- Benchmark Comparison")
        print(f"{'=' * 80}")

        # בודקים אם pymavlink מותקנת
        try:
            import pymavlink
            has_pymavlink = True
        except ImportError:
            has_pymavlink = False
            print("  Note: pymavlink not installed. Skipping pymavlink benchmark.")
            print("  Install with: pip install pymavlink")

        # מריצים את הbenchmark המלא
        run_full_benchmark(
            file_path,
            runs=args.runs,                        # מספר ריצות (ברירת מחדל: 3)
            include_pymavlink=has_pymavlink,        # כולל pymavlink אם מותקנת
            num_workers=args.workers,               # מספר workers (ברירת מחדל: auto)
        )


# ---------------------------------------------------------------------------
# נקודת כניסה -- כאשר מפעילים: python app.py
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    main()
