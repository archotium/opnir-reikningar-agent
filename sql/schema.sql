-- Paid state invoices from opnirreikningar.is, one row per invoice line.
-- The export is flat (6 columns); here it is split into lookup tables so
-- each name is stored once and queries join on integer ids.
--
--   buyer 1---* invoice *---1 vendor
--                  1
--                  |
--                  *
--            invoice_line *---1 cost_type

CREATE TABLE buyer (                -- "Kaupandi": the state agency that paid
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE vendor (               -- "Birgi": the supplier that was paid
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE cost_type (            -- "Tegund": the accounting cost type
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE invoice (              -- one paid invoice
    id             INTEGER PRIMARY KEY,
    buyer_id       INTEGER NOT NULL REFERENCES buyer(id),
    vendor_id      INTEGER NOT NULL REFERENCES vendor(id),
    invoice_number TEXT    NOT NULL,   -- "Númer reiknings"; text, keeps leading zeros
    payment_date   TEXT    NOT NULL,   -- "Dags. greiðslu", ISO yyyy-mm-dd
    UNIQUE (buyer_id, vendor_id, invoice_number, payment_date)
);

CREATE TABLE invoice_line (         -- one line of an invoice
    id           INTEGER PRIMARY KEY,
    invoice_id   INTEGER NOT NULL REFERENCES invoice(id),
    cost_type_id INTEGER NOT NULL REFERENCES cost_type(id),
    amount       INTEGER NOT NULL      -- "Upphæð línu", ISK, can be negative (credit)
);

CREATE INDEX idx_invoice_buyer  ON invoice(buyer_id);
CREATE INDEX idx_invoice_vendor ON invoice(vendor_id);
CREATE INDEX idx_invoice_date   ON invoice(payment_date);
CREATE INDEX idx_line_invoice   ON invoice_line(invoice_id);
CREATE INDEX idx_line_type      ON invoice_line(cost_type_id);

-- The flat shape of the original export, for quick questions.
CREATE VIEW line_flat AS
SELECT b.name  AS buyer,
       i.payment_date,
       v.name  AS vendor,
       t.name  AS cost_type,
       i.invoice_number,
       l.amount
FROM invoice_line l
JOIN invoice   i ON i.id = l.invoice_id
JOIN buyer     b ON b.id = i.buyer_id
JOIN vendor    v ON v.id = i.vendor_id
JOIN cost_type t ON t.id = l.cost_type_id;
