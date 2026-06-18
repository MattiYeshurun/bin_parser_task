# src/utils/constants.py

# חתימת הבתים שמסמנת תחילת הודעה (הפתיח של החבילה)
MSG_HEADER_BYTES = b'\xa3\x95'

# מזהה סוג ההודעה עבור הגדרות פורמט (Format Message Type)
FMT_TYPE_ID = 128

# מקדם החילוק להמרת קואורדינטות גולמיות למעלות גאוגרפיות (10^7)
GPS_COORDINATE_SCALE = 10000000.0

# מספר הבתים שיש לדלג עליהם בתחילת חבילה גולמית (Magic bytes + Type ID)
HEADER_SKIP_BYTES_COUNT = 3

# שם קובץ ברירת המחדל לעבודה ובדיקות
DEFAULT_LOG_FILE_PATH = 'log_file_test_01.bin'