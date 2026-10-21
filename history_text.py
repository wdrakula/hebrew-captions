"""Logical history text and a visual-to-logical map for Tk's bidi presentation."""
from dataclasses import dataclass
from bidi import algorithm as bidi
from languages import is_rtl

@dataclass(frozen=True)
class Presentation:
    original: str
    visual: str
    indices: tuple

    def selected(self, first, last):
        if first == 0 and last == len(self.visual):
            return self.original
        return ''.join(self.original[i] for i in sorted(set(self.indices[first:last])))


def present(text):
    if not is_rtl(text):
        return Presentation(text,text,tuple(range(len(text))))
    visual, indices = [], []
    offset = 0
    # Each hard line gets its own paragraph direction. Mirroring keeps original indices.
    for line in text.splitlines(keepends=True):
        storage = bidi.get_empty_storage()
        level = bidi.get_base_level(line)
        storage['base_level'], storage['base_dir'] = level, ('L','R')[level]
        bidi.get_embedding_levels(line,storage,False,False)
        for i, char in enumerate(storage['chars']): char['logical_index'] = i+offset
        try:
            bidi.explicit_embed_and_overrides(storage,False)
            bidi.resolve_weak_types(storage,False)
            bidi.resolve_neutral_types(storage,False)
            bidi.resolve_implicit_levels(storage,False)
            bidi.reorder_resolved_levels(storage,False)
            bidi.apply_mirroring(storage,False)
        except (AssertionError,KeyError):
            # Unsupported bidi controls must never crash or damage saved/copyable text.
            visual.append(line); indices.extend(range(offset,offset+len(line)))
        else:
            visual.append(''.join(c['ch'] for c in storage['chars']))
            indices.extend(c['logical_index'] for c in storage['chars'])
        offset += len(line)
    return Presentation(text,''.join(visual),tuple(indices))


def timecode(seconds):
    seconds = max(0,int(seconds))
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def format_history(records, metadata, variant='both', timestamps=False):
    if variant not in ('source','translation','both'):
        raise ValueError('Unknown history variant')
    chunks=[]
    for index,(source,translation) in enumerate(records):
        parts = [source] if variant=='source' else [translation] if variant=='translation' else [source,translation]
        if timestamps:
            parts.insert(0,'['+timecode(metadata[index]['seconds'])+']')
        chunks.append('\n'.join(parts))
    return '\n\n'.join(chunks)+ ('\n' if chunks else '')
