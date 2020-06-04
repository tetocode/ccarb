from collections import defaultdict
import itertools
import pickle
from typing import List

from .models import LastTick


def get_instruments(include_fiat=False):
    try:
        tick = LastTick.objects.get(id=LastTick.UUID)
        instruments = defaultdict(dict)
        data = pickle.loads(tick.data)
        if include_fiat:
            for instrument, v in data['fx'].items():
                instruments['fx'][instrument] = True
        for tick in data['crypto']:
            instruments[tick['name']][tick['instrument']] = True
        return instruments
    except LastTick.DoesNotExist:
        return {}


def calc_pairs(currency, ticks: List[dict]):
    results = []

    filtered = [x for x in ticks if x['ask_jpy'] is not None]
    for a, b in itertools.permutations(filtered, 2):
        record = {
            'currency': currency,
            'rate': b['bid_jpy'] / a['ask_jpy'],
            'diff': b['bid_jpy'] - a['ask_jpy'],
            'data': [
                a, b,
            ]
        }
        results.append(record)
    return results


def calc_cycles(currency, ticks: List[dict]):
    results = []
    for a, b, c, d in itertools.permutations(ticks, 4):
        if (a['instrument'][-3:] != d['instrument'][-3:]
                or a['instrument'][:3] != b['instrument'][:3]
                or b['instrument'][-3:] != c['instrument'][-3:]
                or c['instrument'][:3] != d['instrument'][:3]):
            continue

        rate = d['bid'] / a['ask'] * b['bid'] / c['ask']
        results.append({
            'rate': rate,
            'diff': None,
            'data': [a, b, c, d],
        })
    return results
