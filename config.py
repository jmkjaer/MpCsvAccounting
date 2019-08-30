import configparser


class Config:
    """Handler for the configuration file with key-value pairs used in the script."""

    config = configparser.ConfigParser()
    stregsystem = None
    dinero = None

    @classmethod
    def readConfig(cls, configFile="config/config.ini"):
        cls.config.read(configFile)

        try:
            cls.stregsystem = cls.config["stregsystem"]
            cls.dinero = cls.config["dinero"]
        except KeyError:
            raise KeyError(
                "Error in config file. Possibly wrong formatting, or an typo in the path."
            )
