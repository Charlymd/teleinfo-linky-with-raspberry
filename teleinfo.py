#!/usr/bin/env python
# -*- coding: utf-8 -*-
# __author__ = "Sébastien Reuiller"
# __licence__ = "Apache License 2.0"

# Python 3, prerequis : pip install pySerial influxdb
#
# Exemple de trame:
# {
#  'BASE': '123456789'       # Index heure de base en Wh
#  'OPTARIF': 'HC..',        # Option tarifaire HC/BASE
#  'IMAX': '007',            # Intensité max
#  'HCHC': '040177099',      # Index heure creuse en Wh
#  'IINST': '005',           # Intensité instantanée en A
#  'PAPP': '01289',          # Puissance Apparente, en VA
#  'MOTDETAT': '000000',     # Mot d'état du compteur
#  'HHPHC': 'A',             # Horaire Heures Pleines Heures Creuses
#  'ISOUSC': '45',           # Intensité souscrite en A
#  'ADCO': '000000000000',   # Adresse du compteur
#  'HCHP': '035972694',      # index heure pleine en Wh
#  'PTEC': 'HP..'            # Période tarifaire en cours
# }


import serial
import logging
import time
import requests
from datetime import datetime
from influxdb import InfluxDBClient

# clés téléinfo
int_measure_keys = ['BASE','IMAX', 'HCHC', 'IINST', 'PAPP', 'ISOUSC', 'ADCO', 'HCHP']
no_checksum = ['MOTDETAT']

# création du logguer
logging.basicConfig(filename='/var/log/teleinfo/releve.log', level=logging.INFO, format='%(asctime)s %(message)s')
logging.info("Teleinfo starting..")

# connexion a la base de données InfluxDB
client = InfluxDBClient('localhost', 8086)
db = "teleinfo"
connected = False
while not connected:
    try:
        logging.info("Database %s exists?" % db)
        if not {'name': db} in client.get_list_database():
            logging.info("Database %s creation.." % db)
            client.create_database(db)
            logging.info("Database %s created!" % db)
        client.switch_database(db)
        logging.info("Connected to %s!" % db)
    except requests.exceptions.ConnectionError:
        logging.info('InfluxDB is not reachable. Waiting 5 seconds to retry.')
        time.sleep(5)
    else:
        connected = True


def add_measures(measures, time_measure):
    points = []
    for measure, value in measures.items():
        point = {
                    "measurement": measure,
                    "tags": {
                        # identification de la sonde et du compteur
                        "host": "raspberry",
                        "region": "linky"
                    },
                    "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fields": {
                        "value": value
                    }
                }
        points.append(point)

    client.write_points(points)

def calc_checksum(group):
    # Calcul le caractere de controle d'une ligne de trame linky
    # seule l'etiquette et la donnée de chaque ligne doivent etre envoyés en parametre group
    data_unicode = 0
    for data in group:
            data_unicode += ord(data)
    sum_unicode = (data_unicode & 63) + 32
    sum = chr(sum_unicode)
    return sum


def main():
    with serial.Serial(port='/dev/ttyS0', baudrate=1200, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                       bytesize=serial.SEVENBITS, timeout=1) as ser:

        logging.info("Teleinfo is reading on /dev/ttyS0..")

        trame = dict()

        # boucle pour partir sur un début de trame
        line = ser.readline()
        while b'\x02' not in line:  # recherche du caractère de début de trame
            line = ser.readline()

        # lecture de la première ligne de la première trame
        line = ser.readline()

        while True:
            line_str = line.decode("utf-8")
            logging.debug(line_str)
            ar = line_str.split(" ")
            try:
                key = ar[0]
                if key in int_measure_keys :
                    value = int(ar[1])
                else:
                    value = ar[1]
                
                # verification de la somme de controle
                keyandvalue =  ar[0] + " " + ar[1]
                checksum = str(ar[2]).rstrip() # suppression saut de ligne
                checksum2 = calc_checksum(keyandvalue)  
                if (checksum2 == checksum or (key in no_checksum)) :
                    checksum_ok = True
                else :
                    logging.info("Erreur de checksum pour le champ %s" % key)
                    logging.info("Checksum: %s" % checksum)
                    logging.info("Calc_checksum: %s" % checksum2)
                    logging.info("Valeur d'origine: %s" % ar)
                    checksum_ok = False
                
                trame[key] = value
                
                if b'\x03' in line:  # si caractère de fin dans la ligne, on insère la trame dans influx
                    del trame['ADCO']  # adresse du compteur : confidentiel!
                    time_measure = time.time()

                    # insertion dans influxdb
                    if (checksum_ok) : 
                        add_measures(trame, time_measure)

                    # ajout timestamp pour debugger
                    trame["timestamp"] = int(time_measure)
                    logging.debug(trame)

                    trame = dict()  # on repart sur une nouvelle trame
            except Exception as e:
                logging.error("Exception : %s" % e, exc_info=True)
                logging.error("%s %s" % (key,value))
            line = ser.readline()


if __name__ == '__main__':
    if connected:
        main()


