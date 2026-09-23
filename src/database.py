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
    _seed_default_pins_if_empty()
    db.close()

def _seed_default_pins_if_empty():
    if PinMapping.select().count() == 0:
        default_mappings = [
            {'logical_pin': 4,  'physical_pin': 4,  'description': 'Pin 7 | DHT22 / DS18B20 (Sensor Temperatur & Kelembaban)'},
            {'logical_pin': 17, 'physical_pin': 17, 'description': 'Pin 11 | Modul PIR HC-SR501 #1 (Deteksi Gerakan Teras)'},
            {'logical_pin': 27, 'physical_pin': 27, 'description': 'Pin 13 | Modul PIR HC-SR501 #2 (Deteksi Gerakan Ruang Dalam)'},
            {'logical_pin': 22, 'physical_pin': 22, 'description': 'Pin 15 | HC-SR04 (Ultrasonic Trigger Garasi)'},
            {'logical_pin': 23, 'physical_pin': 23, 'description': 'Pin 16 | HC-SR04 (Ultrasonic Echo Garasi)'},
            {'logical_pin': 8,  'physical_pin': 8,  'description': 'Pin 24 | I2C SDA Bus (ADS1115 + PCA9685 + 2x INA226)'},
            {'logical_pin': 9,  'physical_pin': 9,  'description': 'Pin 21 | I2C SCL Bus (ADS1115 + PCA9685 + 2x INA226)'},
            {'logical_pin': 20, 'physical_pin': 20, 'description': 'Pin 38 | RFID PN532 (I2C SDA Pintu Utama)'},
            {'logical_pin': 21, 'physical_pin': 21, 'description': 'Pin 40 | RFID PN532 (I2C SCL Pintu Utama)'},
            {'logical_pin': 18, 'physical_pin': 18, 'description': 'Pin 12 | MAX98357A Audio Amplifier (I2S BCLK)'},
            {'logical_pin': 19, 'physical_pin': 19, 'description': 'Pin 35 | MAX98357A Audio Amplifier (I2S LRCLK)'},
            {'logical_pin': 5,  'physical_pin': 5,  'description': 'Pin 29 | MAX98357A Audio Amplifier (I2S DIN)'}
        ]
        
        # Insert satu persatu
        for mapping in default_mappings:
            PinMapping.create(**mapping)
        print("[xploria_db] Berhasil menyemai (seed) konfigurasi pin default ke dalam SQLite.")

def get_all_pin_mappings():
    db.connect(reuse_if_open=True)
    mappings = {m.logical_pin: m.physical_pin for m in PinMapping.select()}
    db.close()
    return mappings

def update_pin_mapping(logical_pin, physical_pin, description=None, force=False):
    db.connect(reuse_if_open=True)
    
    # Pencegahan Level 1: Cek tabrakan Physical Pin
    existing = PinMapping.select().where(
        (PinMapping.physical_pin == physical_pin) & 
        (PinMapping.logical_pin != logical_pin)
    ).first()
    
    if existing and not force:
        db.close()
        raise ValueError(f"Pin Fisik {physical_pin} sudah digunakan oleh Logical Pin {existing.logical_pin} ({existing.description}).")
        
    if existing and force:
        # Hapus pemetaan yang bertabrakan agar physical pin bisa direbut
        existing.delete_instance()
    
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

