"""Mutate the *spike copy* of AdventureWorks (never the original) for Phase 1 tests.

  insert N    clone N existing orders (header + lines) as new orders dated now
  update N    touch N existing orders (Comment + ModifiedDate)
  delete N    hard-delete N orders (+ lines); original rows saved to deleted_orders.json
Run with: uv run --with pymssql python -I spike/ingest/mutate_source.py <cmd> <N>
Reads MSSQL_* from the environment (source .env first).
"""
import json
import os
import sys

import pymssql

db = os.environ["MSSQL_DB"]
if not db.endswith("_spike"):
    sys.exit(f"refusing to mutate {db!r}: only *_spike databases")

conn = pymssql.connect(os.environ["MSSQL_HOST"], os.environ["MSSQL_USER"], os.environ["MSSQL_PASSWORD"],
                       db, port=os.environ["MSSQL_PORT"])
cur = conn.cursor()
cmd, n = sys.argv[1], int(sys.argv[2])

HDR = ("RevisionNumber,OrderDate,DueDate,ShipDate,Status,OnlineOrderFlag,PurchaseOrderNumber,AccountNumber,"
       "CustomerID,SalesPersonID,TerritoryID,BillToAddressID,ShipToAddressID,ShipMethodID,CreditCardID,"
       "CreditCardApprovalCode,CurrencyRateID,SubTotal,TaxAmt,Freight,Comment")
DET = "CarrierTrackingNumber,OrderQty,ProductID,SpecialOfferID,UnitPrice,UnitPriceDiscount"


def pick(k, newest=False):
    order = "SalesOrderID desc" if newest else "newid()"
    cur.execute(f"select top {k} SalesOrderID from Sales.SalesOrderHeader order by {order}")
    return [r[0] for r in cur.fetchall()]


if cmd == "insert":
    new_ids = []
    for oid in pick(n):
        cur.execute(f"insert Sales.SalesOrderHeader ({HDR},ModifiedDate) "
                    f"select {HDR},getdate() from Sales.SalesOrderHeader where SalesOrderID=%s", (oid,))
        cur.execute("select cast(scope_identity() as int)")
        nid = cur.fetchone()[0]
        cur.execute(f"insert Sales.SalesOrderDetail (SalesOrderID,{DET},ModifiedDate) "
                    f"select %s,{DET},getdate() from Sales.SalesOrderDetail where SalesOrderID=%s", (nid, oid))
        new_ids.append(nid)
    # OrderDate of a clone: make it "now" so it lands in the recent window
    cur.execute("update Sales.SalesOrderHeader set OrderDate=getdate(),DueDate=dateadd(day,12,getdate()),"
                f"ShipDate=dateadd(day,7,getdate()) where SalesOrderID in ({','.join(map(str, new_ids))})")
    conn.commit()
    print("inserted", new_ids)
elif cmd == "update":
    ids = pick(n)
    cur.execute(f"update Sales.SalesOrderHeader set Comment='spike-updated', ModifiedDate=getdate() "
                f"where SalesOrderID in ({','.join(map(str, ids))})")
    conn.commit()
    print("updated", ids)
elif cmd == "delete":
    ids = pick(n)
    inlist = ",".join(map(str, ids))
    saved = {}
    for t in ("Sales.SalesOrderHeaderSalesReason", "Sales.SalesOrderDetail", "Sales.SalesOrderHeader"):
        cur.execute(f"select * from {t} where SalesOrderID in ({inlist})")
        cols = [d[0] for d in cur.description]
        saved[t] = [dict(zip(cols, map(str, r), strict=True)) for r in cur.fetchall()]
        cur.execute(f"delete from {t} where SalesOrderID in ({inlist})")
    conn.commit()
    json.dump(saved, open("spike/ingest/deleted_orders.json", "w"), indent=1)
    print("deleted", ids)
