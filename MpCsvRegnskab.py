from pathlib import Path
import csv

def readTransactions(file):
    transactions = []
    next(file)
    next(file)
    reader = csv.reader(file, delimiter=";")
    for row in reader:
        if row[0] == "Salg" or row[0] == "Refundering" or row[0] == "Gebyr":
            continue
        transactions.append(row)
    
    return transactions


filename = input("File name (on Desktop):\n> ")
# appendix = input("\nAppendix number start:\n> ")
readPath = Path.cwd().parent
writePath = str(readPath) + "/dinero" + filename
file = open("test.csv", "r", newline='', encoding="utf-16")
transactions = readTransactions(file)
for x in transactions:
    print(x)
