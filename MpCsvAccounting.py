import csv
import datetime
import locale
from pathlib import Path


class Account(str):
    NORDJYSKE = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


def prepareCsvReader(filePath):
    file = open(filePath, "r", newline='', encoding="utf-16-le")
    next(file)
    next(file)

    return csv.reader(file, delimiter=";")


def isRegistration(transaction):
    return "tilmeld" in transaction[2].lower() or "indmeld" in transaction[2].lower()


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
    file = open(filePath, "w", newline='')
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter


def floatToLocalStringDecimal(float):
    return str(float).replace(".", ",")


def writeTransactions(filePath, appendixStart, transactions, registrationTransferCounts):
    currTransferIndex = 0
    currAppendix = appendixStart
    csvWriter = prepareCsvWriter(filePath)

    csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])

    for i, transaction in enumerate(transactions):
        # A registration transfer can happen a number of times in a day
        registrationTransferDate = registrationTransferCounts[0][0]
        registrationsCount = int(registrationTransferCounts[0][1])
        transAmount = locale.atof(transaction[0])
        voucherAmount = transAmount + locale.atof(transaction[2])
        transactionDate = datetime.datetime.strptime(transaction[1], "%d-%m-%Y")
        headlineDate = str(transactionDate.day) + "-" + str(transactionDate.month)
        transactionDate = transaction[1]
        
        csvWriter.writerow([currAppendix, transactionDate, "MP " + headlineDate.zfill(5), Account.NORDJYSKE, floatToLocalStringDecimal(transAmount), None])
        
        if transaction[1] != registrationTransferDate:
            csvWriter.writerow([currAppendix, transactionDate, "Gavekort", Account.GAVEKORT, "-" + floatToLocalStringDecimal(voucherAmount), None])
        else:
            registrationFees = 200*registrationsCount
            voucherAmount = transAmount + locale.atof(transaction[2]) - registrationFees

            csvWriter.writerow([currAppendix, transaction[1], "Gavekort", Account.GAVEKORT, "-" + floatToLocalStringDecimal(voucherAmount), None])
            csvWriter.writerow([currAppendix, registrationTransferDate, "Tilmeldingsgebyr", Account.SALG, "-" + floatToLocalStringDecimal(registrationFees), None])

            del registrationTransferCounts[0]

        csvWriter.writerow([currAppendix, transactionDate, "MP-gebyr", Account.GEBYRER, transaction[2], None])

        currAppendix += 1


def main():
    locale.setlocale(locale.LC_NUMERIC, "en_DK.UTF-8")

    filename = input("File name (on Desktop):\n> ")
    appendixStart = int(input("\nAppendix number start:\n> "))
    readPath = str(Path.cwd()) + "/" + filename
    writePath = str(Path.cwd()) + "/dinero_" + filename

    transactionsByDate = readTransactionsFromFile(readPath)

    # writeTransactions(writePath, appendixStart, transactions, registrationTransferCounts)

    print("\nDone writing to " + writePath)


if __name__ == "__main__":
    main()
