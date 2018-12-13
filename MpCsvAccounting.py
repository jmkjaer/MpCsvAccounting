import csv
import datetime
import holidays
import locale
from pathlib import Path


HOLIDAYS_DK = holidays.DK()


class Account(str):
    """String constants for Dinero's bank accounts."""

    BANK = "55000"
    GAVEKORT = "63080"
    GEBYRER = "7220"
    SALG = "1000"


def prepareCsvReader(filePath):
    """Prepares the CSV reader by opening the file and skipping two lines."""

    file = open(filePath, "r", newline="", encoding="utf-16-le")
    next(file)
    next(file)

    return csv.reader(file, delimiter=";")


def readTransactionsFromFile(filePath):
    """Returns transactions in batches read from the CSV file exported by MP.
    
    We are not interested in the bank transactions or the fees listed by MP, \
    only the actual user transactions (sales, or "Salg"), since they will be \
    manipulated and used for calculation later.
    
    Returns a list of lists of user transactions bundled in transaction \
    batches before bank transfer.
    """

    reader = prepareCsvReader(filePath)
    transactions = []
    transactionsByBatch = []

    for row in reader:
        if row[0] == "Salg":
            # Amount, date, message, MP fee
            transactions.append((row[3], row[6], row[9], row[10]))
            continue
        elif row[0] == "Overførsel":
            # The imported CSV starts with a "Gebyr" and an "Overførsel"
            if len(transactions) > 0:
                transactionsByBatch.append(transactions)
                transactions = []
            continue
        elif row[0] == "Gebyr":
            continue
        else:
            raise ValueError("Unknown transaction type")
    # The imported CSV ends with a batch of sales with no "Overførsel"
    transactionsByBatch.append(transactions)

    return transactionsByBatch


def prepareCsvWriter(filePath):
    """Prepares the CSV writer by opening the file and setting delimiters."""

    file = open(filePath, "w", newline="")
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter


def floatToLocalStringDecimal(float):
    """Replaces decimal point with comma, used in import and export CSV."""

    return str(float).replace(".", ",")


def isRegistration(transaction):
    """Finds out if the transaction is part of a registration.
    
    Searches for the substrings "tilmeld" and "indmeld" in the MP \
    transaction comment.
    """

    return "tilmeld" in transaction[2].lower() or "indmeld" in transaction[2].lower()


def calculateBatchInfo(batch, registrationFee=200):
    """Returns important information from a batch of transactions.
    
    Calculates and returns the amount transferred to the bank, the fees by \
    MP, the registration fees paid by the members, and the voucher amount for \
    the members.
    """

    registrationFees = 0
    voucherAmount = 0
    mpFees = 0
    toBank = 0

    for transaction in batch:
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


def nextBusinessDay(date):
    """Returns the next business day for bank transfer.
    
    With help from https://stackoverflow.com/a/42824111
    """

    nextDay = date.date() + datetime.timedelta(days=1)
    while nextDay.weekday() in holidays.WEEKEND or nextDay in HOLIDAYS_DK:
        nextDay += datetime.timedelta(days=1)

    return nextDay


def writeTransactions(filePath, appendixStart, transactionsByBatch):
    """Writes the information gathered throughout the script to a CSV file.
    
    The resulting CSV file is recognized by Dinero's journal entry CSV \
    import. The written information is in Danish.
    """

    currAppendix = appendixStart
    csvWriter = prepareCsvWriter(filePath)

    csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])

    for batch in transactionsByBatch:
        batchDate = datetime.datetime.strptime(batch[0][1], "%d-%m-%Y")
        bankTransferDate = nextBusinessDay(batchDate)
        toBank, mpFees, registrationFees, voucherAmount = calculateBatchInfo(batch)

        csvWriter.writerows(
            [
                [
                    currAppendix,
                    bankTransferDate,
                    "MP " + (str(batchDate.day) + "-" + str(batchDate.month)).zfill(5),
                    Account.BANK,
                    floatToLocalStringDecimal(toBank),
                    None,
                ],
                [
                    currAppendix,
                    bankTransferDate,
                    "Gavekort",
                    Account.GAVEKORT,
                    "-" + floatToLocalStringDecimal(voucherAmount),
                    None,
                ],
            ]
        )

        if registrationFees > 0:
            csvWriter.writerow(
                [
                    currAppendix,
                    bankTransferDate,
                    "Tilmeldingsgebyr",
                    Account.SALG,
                    "-" + floatToLocalStringDecimal(registrationFees),
                    None,
                ]
            )

        csvWriter.writerow(
            [
                currAppendix,
                bankTransferDate,
                "MP-gebyr",
                Account.GEBYRER,
                floatToLocalStringDecimal(mpFees),
                None,
            ]
        )

        currAppendix += 1


def main():
    """Reads a CSV by MP and writes a CSV recognizable by Dinero.
    
    The locale is set to be able to convert the Danish decimal numbers into \
    floats instead of replacing the separator ourselves. May be removed in \
    the future.
    """
    locale.setlocale(locale.LC_NUMERIC, "en_DK.UTF-8")

    filename = input("File name (from " + str(Path.cwd()) + "):\n> ")
    appendixStart = int(input("\nAppendix number start:\n> "))
    readPath = Path.cwd() / filename
    writePath = Path.cwd() / ("dinero_" + filename)

    transactionsByBatch = readTransactionsFromFile(readPath)

    writeTransactions(str(writePath), appendixStart, transactionsByBatch)

    print("\nDone writing to " + str(writePath))


if __name__ == "__main__":
    main()
