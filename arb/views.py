from collections import OrderedDict, defaultdict
import json
import pickle
from pprint import pprint

from django.http import HttpResponse, HttpRequest
from django.shortcuts import render

from .models import Config, Filter, LastTick
from .utils import get_instruments, calc_cycles, calc_pairs


def get(request: HttpRequest, currency: str):
    n = int(request.GET.get('n', 100) or 100)
    currency = currency.upper()

    try:
        last_tick = LastTick.objects.get(id=LastTick.UUID)
        data = pickle.loads(last_tick.data)

        config, _ = Config.objects.get_or_create(currency=currency)
        enabled_instruments = defaultdict(lambda: defaultdict(lambda: False))
        filters = Filter.objects.filter(config=config).all()
        if filters:
            for x in filters:
                enabled_instruments[x.name][x.instrument] = True

        fx_rates = data['fx']
        ticks = []
        for tick in data['crypto']:
            if not (tick['instrument'].startswith(currency) or tick['name'] == currency.lower()):
                continue
            if enabled_instruments[tick['name']][tick['instrument']]:
                ticks.append(tick)
        if currency.lower() in enabled_instruments:
            # not crypto
            records = calc_cycles(currency, ticks)
        else:
            records = calc_pairs(currency, ticks)

        def is_enabled(x):
            for item in x['data']:
                if not enabled_instruments[item['name']][item['instrument']]:
                    return False
            return True

        records = list(filter(is_enabled, records))
        records.sort(key=lambda x: -x['rate'])
        if currency == 'BTC' and records:
            if records[0]['rate'] > 1.10:
                pprint(data)
        json_str = json.dumps({
            'created_at': last_tick.updated_at.isoformat(),
            'records': records[:n]
        }, separators=(',', ':'))
    except LastTick.DoesNotExist:
        json_str = json.dumps({
            'created_at': None,
            'records': []
        }, separators=(',', ':'))
    return HttpResponse(json_str, content_type='application/json; charset=UTF-8')


def index(request):
    return render(request, 'arb/index.html', {})


def main(request: HttpRequest):
    all_filter_instruments = {}
    configs = {}
    for config in Config.objects.all():
        currency = config.currency.upper()
        configs[currency] = json.loads(config.data) if config.data else {
            'interval': 20,
            'row_n': 20,
            'rate_threshold': 1.0,
        }
        enabled_instruments = defaultdict(lambda: defaultdict(lambda: False))
        filters = Filter.objects.filter(config=config).all()
        if filters:
            for x in filters:
                enabled_instruments[x.name][x.instrument] = True
        instruments = OrderedDict(sorted(get_instruments(include_fiat=False).items()))
        filter_instruments = OrderedDict()
        for name, v_dict in instruments.items():
            filter_instruments[name] = OrderedDict()
            for instrument in sorted(v_dict.keys()):
                if instrument.startswith(currency):
                    filter_instruments[name][instrument] = enabled_instruments[name][instrument]
                elif currency.lower() == name:
                    filter_instruments[name][instrument] = enabled_instruments[name][instrument]
        all_filter_instruments[currency] = filter_instruments
    context = {
        'bell': 'arb/bell.wav',
        'dialog': 'arb/dialog.wav',
        'filter_instruments': all_filter_instruments,
        'configs': configs,
    }
    return render(request, 'arb/main.html', context)


def config(request: HttpRequest, currency):
    if request.method == 'POST':
        return config_post(request, currency)
    currency = request.method + currency
    json_str = json.dumps(currency, separators=(',', ':'))
    return HttpResponse(json_str, content_type='application/json; charset=UTF-8')


def config_post(request: HttpRequest, currency):
    currency = currency.upper()
    try:
        config = Config.objects.get(currency=currency)
    except Config.DoesNotExist:
        config = Config(currency=currency).save()
    data = request.POST.get('config')
    if data:
        config.data = data
        config.save()
    data = request.POST.get('filter_instruments')
    if data:
        filter_instruments = json.loads(data)
        for k, v in filter_instruments.items():
            name = k.split('_')[0]
            instrument = k[len(name) + 1:]
            if v:
                Filter(config=config, name=name, instrument=instrument).save()
            else:
                Filter.objects.filter(config=config, name=name, instrument=instrument).delete()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json; charset=UTF-8')
