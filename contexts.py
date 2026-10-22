"""Small subject hints for the existing, single translation request."""
CONTEXTS = {
    'neutral': ('Нейтральный', 'General conversation; use neutral terminology.'),
    'math': ('Учёба — математика', 'Mathematics lecture. Use established mathematical terminology in the target language. Preserve formulae, symbols, variable names, numbers and negations. Do not guess uncertain letters or change mathematical claims.'),
    'science': ('Наука и техника', 'Science and technology. Use established scientific and technical terminology; preserve quantities, units and identifiers.'),
    'cinema': ('Кино и сериалы', 'Film or TV dialogue. Preserve tone, colloquial meaning and idioms; do not translate idioms literally when inappropriate.'),
    'news': ('Новости и политика', 'News and politics. Use standard political terminology and established names of institutions; preserve attribution and uncertainty.'),
}
DEFAULT_CONTEXT = 'math'

def context_prompt(code):
    if code not in CONTEXTS:
        raise ValueError('Unknown translation context')
    return CONTEXTS[code][1]
