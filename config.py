import configparser

# Handler module for the configuration file with key-value pairs used in the script."""

config = configparser.ConfigParser()
config.read("config/config.ini")

stregsystem = config["stregsystem"]
dinero = config["dinero"]
