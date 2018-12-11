from pathlib import Path
import csv

def readTransactionsFromFile(filePath):
    transactions = []
    registrationTransfers = []
    reader = prepareCsvReader(filePath)
    
    for row in reader:
        if row[0] == "Refundering" or row[0] == "Gebyr":
            continue
        if "tilmeld" in row[9].lower() or "indmeld" in row[9].lower():
            registrationTransfers.append(row[6])
            continue
        if row[0] == "Salg":
            continue

        transactions.append([row[3], row[6], row[10]])

    return transactions, registrationTransfers

def writeTransactions(appendixStart, transactions, transactionTransfers):
    currTransferIndex = 0
    currAppendix = appendixStart
    csvWriter = prepareCsvWriter()
    csvWriter.writerow(["Bilag nr.", "Dato", "Tekst", "Konto", "Beløb", "Modkonto"])

    for transaction in transactions:
        csvWriter.writerow([currAppendix, transaction[1], "MP test", "55000", transaction[0]])
        csvWriter.writerow([currAppendix, transaction[1], "Overførsler", "63080", transaction[0]])
        if transactionTransfers[currTransferIndex] == transaction[1]:
            csvWriter.writerow([currAppendix, transaction[1], "Tilmeldingsgebyr", "1000", ])
        csvWriter.writerow([currAppendix, transaction[1], "Gebyr", "7220", transaction[2]])

        currAppendix += 1

def prepareCsvWriter():
    file = open("filePath.csv", "w", newline='')
    csvWriter = csv.writer(file, delimiter=";")
    return csvWriter

def prepareCsvReader(filePath):
    file = open(filePath, "r", newline='', encoding="utf-16-le")
    next(file)
    next(file)

    return csv.reader(file, delimiter=";")


filename = input("File name (on Desktop):\n> ")
appendixStart = int(input("\nAppendix number start:\n> "))
readPath = str(Path.cwd()) + "/" + filename
writePath = readPath + "/dinero_" + filename

transactions, registrationTransfers = readTransactionsFromFile(readPath)

transfers = [[transfer, registrationTransfers.count(transfer)] for transfer in set(registrationTransfers)]
transfers.sort(key=lambda x: x[0])

writeTransactions(appendixStart, transactions, registrationTransfers)


print(test)
# print(test1)