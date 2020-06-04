import pickle
import uuid
import zlib

from django.db import models


class LastTick(models.Model):
    UUID = 'b814f1f1-91ae-4721-a60d-7c5824697dbc'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    data = models.BinaryField()


class Config(models.Model):
    currency = models.CharField(max_length=255, db_index=True, unique=True)
    data = models.CharField(max_length=1024, default='')


class Filter(models.Model):
    config = models.ForeignKey(Config, related_name='filter')
    name = models.CharField(max_length=255)
    instrument = models.CharField(max_length=255)


class Record(models.Model):
    created_at = models.DateTimeField()
    currency = models.CharField(max_length=255)
    rate = models.FloatField()
    diff = models.FloatField(null=True)
    data = models.BinaryField()

    class Meta:
        index_together = (('created_at', 'currency', 'rate'),
                          ('currency', 'created_at', 'rate'),)

    def to_dict(self):
        return {
            'created_at': self.created_at.isoformat(),
            'currency': self.currency,
            'rate': self.rate,
            'diff': self.diff,
            'data': pickle.loads(zlib.decompress(self.data)),
        }

    def to_dict_for_json(self):
        d = self.to_dict()
        for x in d['data']:
            x['created_at'] = x['created_at'].isoformat()
            del x['created_at']
            del x['is_fiat']
            del x['qty_threshold']
            del x['best_ask']
            del x['best_ask_qty']
            del x['best_bid']
            del x['best_bid_qty']
        del d['created_at']
        return d

    @classmethod
    def from_dict(cls, d):
        return Record(created_at=d['created_at'],
                      currency=d['currency'],
                      rate=d['rate'],
                      diff=d['diff'],
                      data=zlib.compress(pickle.dumps(d['data'])))
