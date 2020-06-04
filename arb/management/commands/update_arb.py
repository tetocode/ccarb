from collections import defaultdict
import itertools
import logging
import pickle
from pprint import pprint
import time
from typing import List
import zlib

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.forms import model_to_dict
from docopt import docopt
import pyutil

from arb.models import Record, Config, Filter, Tick


class Command(BaseCommand):
    currencies = []
    interval = 30

    def run_from_argv(self, argv):
        args = docopt("""
        Usage:
          {f} [options]

        Options:
          --currencies CURRENCIES  [default: BTC,ETH,quoine]
          --interval SEC  [default: 0.5]
          
        """.format(f=argv[1]), argv[2:])

        print('#arguments')
        pprint(args)
        self.currencies = args['--currencies'].split(',')
        self.interval = float(args['--interval'])
        self.start()

    def start(self):
        i = 0
        while True:
            for currency in self.currencies:
                try:
                    self.action(currency, i)
                except Exception as e:
                    logging.exception(str(e))
            i += 1
            time.sleep(self.interval)

    def action(self, currency, i):
        if i % 100 == 0:
            pass
        try:
            config = Config.objects.get(currency=currency)
        except Config.DoesNotExist:
            print('{} no config'.format(currency))
            return

        max_time = Tick.objects.aggregate(Max('created_at'))
        dt = max_time['created_at__max']
        records = Record.objects.filter(created_at=dt, currency=currency).all()
        if records.count():
            return
        print('#', currency, pyutil.jst_now_aware())

        enabled_instruments = defaultdict(lambda: defaultdict(lambda: False))
        filters = Filter.objects.filter(config=config).all()
        if filters:
            for x in filters:
                enabled_instruments[x.name][x.instrument] = True

        ticks = []
        for tick in Tick.objects.filter(created_at=dt).all():
            if True:
                if not (tick.instrument.startswith(currency) or tick.name == currency):
                    continue
                if enabled_instruments[tick.name][tick.instrument]:
                    ticks.append(tick)
            else:
                if tick.is_fiat:
                    continue
                if currency == tick.instrument[:3] or currency == tick.name:
                    ticks.append(tick)

        if currency in enabled_instruments:
            # not cypto
            records = self.calc_cycles(dt, currency, ticks)
        else:
            records = self.calc_pairs(dt, currency, ticks)

        with transaction.atomic():
            print('#', currency, len(records))
            Record.objects.bulk_create(records)

    def calc_pairs(self, dt, currency, ticks: List[Tick]):
        results = []

        filtered = [x for x in ticks if x.ask_jpy is not None]
        for a, b in itertools.permutations(filtered, 2):
            record = Record(created_at=dt,
                            currency=currency,
                            rate=b.bid_jpy / a.ask_jpy,
                            diff=b.bid_jpy - a.ask_jpy,
                            data=zlib.compress(pickle.dumps([
                                model_to_dict(a),
                                model_to_dict(b),
                            ])))
            results.append(record)
        return results

    def calc_cycles(self, dt, currency, ticks: List[Tick]):
        results = []
        for a, b, c, d in itertools.permutations(ticks, 4):
            if (a.instrument[-3:] != d.instrument[-3:]
                    or a.instrument[:3] != b.instrument[:3]
                    or b.instrument[-3:] != c.instrument[-3:]
                    or c.instrument[:3] != d.instrument[:3]):
                continue

            rate = d.bid / a.ask * b.bid / c.ask
            results.append(Record(created_at=dt,
                                  currency=currency,
                                  rate=rate,
                                  diff=None,
                                  data=zlib.compress(pickle.dumps([
                                      model_to_dict(a),
                                      model_to_dict(b),
                                      model_to_dict(c),
                                      model_to_dict(d),
                                  ]))))
        return results

    def reload_markets(self):
        def reload(broker):
            broker.load_markets(reload=True)

        list(self.pool.map(reload, self.brokers.values()))

        instruments = {}
        for name, broker in self.brokers.items():
            markets = broker.load_markets()
            for instrument, data in markets.items():
                base, quote = data['base'], data['quote']
                if base not in self.crypts or quote not in self.fiats:
                    continue
                if name == 'bitmex' and '.' in instrument:
                    continue
                if name == 'coincheck' and instrument != 'BTC/JPY':
                    continue
                if name == 'kraken' and '/' not in instrument:
                    continue
                instruments.setdefault(name, {})[instrument] = data
        self.brokers_instruments = instruments
        return instruments

    def update_fx_rates_loop(self):
        while True:
            try:
                self.update_fx_rates()
            except Exception as e:
                logging.exception(str(e))
            time.sleep(5)

    def update_fx_rates(self):
        instruments = ['{}_JPY'.format(x) for x in self.fiats if x != 'JPY']
        prices = self.oanda.get_prices(instruments=','.join(instruments))['prices']
        fx_rates = [{
            'instrument': x['instrument'].replace('_', '/'),
            'ask': x['ask'],
            'bid': x['bid'],
            'mid': (x['ask'] + x['bid']) / 2,
            'base': x['instrument'][:3],
            'quote': x['instrument'][-3:],
        } for x in prices]
        fx_rates.append({
            'instrument': 'JPY/JPY',
            'ask': 1,
            'bid': 1,
            'mid': 1,
            'base': 'JPY',
            'quote': 'JPY',
        })
        results = {}
        for a, b in itertools.permutations(fx_rates, 2):
            instrument = '{}/{}'.format(a['base'], b['base'])
            results[instrument] = {
                'name': 'oanda',
                'instrument': instrument,
                'is_fiat': True,
                'ask': a['ask'] / b['bid'],
                'bid': a['bid'] / b['ask'],
                'mid': (a['ask'] / b['bid'] + a['bid'] / b['ask']) / 2,
                'base': a['base'],
                'quote': b['base'],
            }
        results['JPY/JPY'] = {
            'name': '',
            'instrument': 'JPY/JPY',
            'is_fiat': True,
            'ask': 1,
            'bid': 1,
            'mid': 1,
            'base': 'JPY',
            'quote': 'JPY',
        }
        self.fx_rates = results

    def get_ticks(self):
        arg_list = []
        for name, instruments in self.brokers_instruments.items():
            for instrument in instruments:
                arg_list.append((name, instrument))

        def get_order_book(arg):
            name, instrument = arg
            broker = self.brokers[name]
            try:
                book = broker.fetchOrderBook(instrument)
                book['name'] = broker.id
                book['instrument'] = instrument
                book['base'] = base = self.brokers_instruments[name][instrument]['base']
                book['quote'] = self.brokers_instruments[name][instrument]['quote']
                if base == 'BTC':
                    threshold = 1
                elif base == 'ETH':
                    threshold = 15
                else:
                    assert False, (name, instrument, base)
                if not book['asks'] or not book['bids']:
                    print('no data', arg)
                    return None
                if name == 'bitmex':
                    if instrument == 'BTC/USD':
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2
                    elif instrument.startswith('XBT'):
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2
                    elif instrument.startswith('XBJ'):
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2 / 100
                book['qty_threshold'] = threshold
                book['best_ask'] = book['asks'][0][0]
                book['best_ask_qty'] = book['asks'][0][1]
                book['best_bid'] = book['bids'][0][0]
                book['best_bid_qty'] = book['bids'][0][1]
                for k in ['ask', 'bid']:
                    book[k] = None
                    book[k + '_qty'] = None
                    qty = 0.0
                    for x in book[k + 's']:
                        qty += x[1]
                        if qty >= threshold:
                            book[k] = x[0]
                            book[k + '_qty'] = qty
                            break
                    else:
                        print('no data', arg)
                        return None
                    del book[k + 's']
                return book
            except Exception:
                return None

        return list(filter(bool, self.pool.map(get_order_book, arg_list)))
