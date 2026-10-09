"""Explicit language choices shared by UI and API requests."""
LANGUAGES = {
    'he': ('Иврит', 'Hebrew'),
    'en': ('Английский', 'English'),
    'fr': ('Французский', 'French'),
    'es': ('Испанский', 'Spanish'),
    'ru': ('Русский', 'Russian'),
}
TRANSLATORS = {'gpt-4o-mini': 'gpt-4o-mini — дешевле', 'gpt-4.1-mini': 'gpt-4.1-mini — дороже'}

def language(code):
    if code not in LANGUAGES:
        raise ValueError('Неподдерживаемый язык')
    return LANGUAGES[code][1]

def is_rtl(text):
    import unicodedata
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)

def display_text(text):
    # Apply bidi only to RTL text; preserve Latin/Cyrillic punctuation as supplied.
    if is_rtl(text):
        from bidi.algorithm import get_display
        return get_display(text)
    return text
