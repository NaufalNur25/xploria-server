import os
from peewee import SqliteDatabase, Model, IntegerField, CharField

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pin_config.db')

db = SqliteDatabase(DB_PATH)

class BaseModel(Model):
    class Meta:
        database = db

class PinMapping(BaseModel):
    logical_pin = IntegerField(unique=True)
    physical_pin = IntegerField()
    description = CharField(null=True, default="")

def init_db():
    db.connect()
    db.create_tables([PinMapping], safe=True)
    db.close()

def get_all_pin_mappings():
    db.connect(reuse_if_open=True)
    mappings = {m.logical_pin: m.physical_pin for m in PinMapping.select()}
    db.close()
    return mappings

def update_pin_mapping(logical_pin, physical_pin, description=None):
    db.connect(reuse_if_open=True)
    mapping, created = PinMapping.get_or_create(logical_pin=logical_pin, defaults={'physical_pin': physical_pin, 'description': description or ""})
    if not created:
        mapping.physical_pin = physical_pin
        if description is not None:
            mapping.description = description
        mapping.save()
    db.close()

def delete_pin_mapping(logical_pin):
    db.connect(reuse_if_open=True)
    query = PinMapping.delete().where(PinMapping.logical_pin == logical_pin)
    query.execute()
    db.close()
