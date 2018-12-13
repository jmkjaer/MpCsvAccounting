import csv
import datetime
import locale
from pathlib import Path


class Account(str):
    BANK = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


def prepareCsvReader(filePath):
    file = open(filePath, "r", newline="", encoding="utf-16-le")
    next(file)
    next(file)

    return csv.reader(file, delimiter=";")


def readTransactionsFromFile(filePath):
    reader = prepareCsvReader(filePath)
    transactions = []
    transactionsByDate = []

    for row in reader:
        if row[0] == "Salg":
            transactions.append((row[3], row[6], row[9], row[10]))
            continue
        elif row[0] == "Overførsel":
            # The imported CSV starts with a "Gebyr" and an "Overførsel"
            if len(transactions) > 0:
                transactionsByDate.append(transactions)
                transactions = []
            continue
        elif row[0] == "Gebyr":
            continue
        else:
            raise ValueError("Unknown transaction type")
    # The imported CSV ends with a bunch of sales with no "Overførsel"
    transactionsByDate.append(transactions)

    return transactionsByDate


def prepareCsvWriter(filePath):
    file = open(filePath, "w", newline="")
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter


def floatToLocalStringDecimal(float):
    return str(float).replace(".", ",")


def isRegistration(transaction):
    return "tilmeld" in transaction[2].lower() or "indmeld" in transaction[2].lower()


def calculateDay(day):
    registrationFee = 200
    registrationFees = 0
    voucherAmount = 0
    mpFees = 0
    toBank = 0

    for transaction in day:
        mpFee = locale.atof(transaction[3])
        transAmount = locale.atof(transaction[0])

        mpFees += mpFee
        toBank += transAmount - mpFee

        if isRegistration(transaction):
            registrationFees += registrationFee
            voucherAmount += transAmount - registrationFee
        else:
            voucherAmount += transAmount

    return (toBank, mpFees, registrationFees, voucherAmount)


def writeTransactions(filePath, appendixStart, transactionsByDay):
    currTransferIndex = 0
    currAppendix = appendixStart
    csvWriter = prepareCsvWriter(filePath)

    csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])

    for day in transactionsByDay:
        dayDate = datetime.datetime.strptime(day[0][1], "%d-%m-%Y")
        headlineDate = str(dayDate.day) + "-" + str(dayDate.month)
        toBank, mpFees, registrationFees, voucherAmount = calculateDay(day)

        csvWriter.writerow(
            [
                currAppendix,
                dayDate,
                "MP " + headlineDate.zfill(5),
                Account.BANK,
                floatToLocalStringDecimal(toBank),
                None,
            ]
        )

        csvWriter.writerow(
            [
                currAppendix,
                dayDate,
                "Gavekort",
                Account.GAVEKORT,
                "-" + floatToLocalStringDecimal(voucherAmount),
                None,
            ]
        )

        if registrationFees > 0:
            csvWriter.writerow(
                [
                    currAppendix,
                    dayDate,
                    "Tilmeldingsgebyr",
                    Account.SALG,
                    "-" + floatToLocalStringDecimal(registrationFees),
                    None,
                ]
            )

        csvWriter.writerow(
            [
                currAppendix,
                dayDate,
                "MP-gebyr",
                Account.GEBYRER,
                floatToLocalStringDecimal(mpFees),
                None,
            ]
        )

        currAppendix += 1


def main():
    locale.setlocale(locale.LC_NUMERIC, "en_DK.UTF-8")

    filename = input("File name (on Desktop):\n> ")
    appendixStart = int(input("\nAppendix number start:\n> "))
    readPath = str(Path.cwd()) + "/" + filename
    writePath = str(Path.cwd()) + "/dinero_" + filename

    transactionsByDay = readTransactionsFromFile(readPath)

    writeTransactions(writePath, appendixStart, transactionsByDay)

    print("\nDone writing to " + writePath)


if __name__ == "__main__":
    main()
