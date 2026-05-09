import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "materials.db"

SEED_DATA = [
    # (name, category, E_GPa, nu, rho_kgm3, alpha_1e6K, k_WmK, Cp_JkgK, yield_MPa, UTS_MPa, source)
    ("Structural Steel",        "Steel",    200.0, 0.30, 7850, 12.0,  60.5, 434,  250,  460, "ANSYS defaults"),
    ("Stainless Steel 316L",    "Steel",    193.0, 0.27, 7980, 16.0,  16.3, 500,  170,  485, "MatWeb"),
    ("High Strength Steel S690","Steel",    210.0, 0.30, 7850, 12.0,  50.0, 490,  690,  770, "EN 10025-6"),
    ("Cast Iron Gray",          "Iron",     110.0, 0.26, 7200, 11.0,  46.0, 544,    0,  179, "MatWeb"),
    ("Aluminum Alloy 6061-T6",  "Aluminum",  68.9, 0.33, 2700, 23.6, 167.0, 896,  276,  310, "ASM"),
    ("Aluminum Alloy 7075-T6",  "Aluminum",  71.7, 0.33, 2810, 23.6, 130.0, 960,  503,  572, "ASM"),
    ("Aluminum Alloy 2024-T3",  "Aluminum",  73.1, 0.33, 2780, 23.2, 121.0, 875,  345,  483, "ASM"),
    ("Aluminum 5052-H32",       "Aluminum",  70.3, 0.33, 2680, 23.8, 138.0, 880,  193,  228, "ASM"),
    ("Titanium Ti-6Al-4V",      "Titanium", 113.8, 0.342,4430,  8.6,   6.7, 560,  880,  950, "ASM"),
    ("Titanium Grade 2 CP",     "Titanium", 105.0, 0.37, 4510,  8.6,  16.0, 520,  275,  345, "ASM"),
    ("Copper C11000",           "Copper",   115.0, 0.34, 8900, 17.0, 388.0, 385,   69,  220, "MatWeb"),
    ("Brass C26000",            "Copper",   110.0, 0.34, 8530, 20.0, 120.0, 375,  310,  525, "MatWeb"),
    ("Magnesium AZ31B",         "Magnesium", 45.0, 0.35, 1770, 26.0,  96.0,1000,  200,  260, "ASM"),
    ("Inconel 718",             "Nickel",   200.0, 0.29, 8190, 13.0,  11.4, 435, 1034, 1240, "Special Metals"),
    ("HDPE",                    "Polymer",    0.8, 0.42,  960,150.0,   0.5,1900,   26,   37, "MatWeb"),
    ("Polycarbonate PC",        "Polymer",    2.4, 0.37, 1200, 68.0,   0.2,1250,   55,   65, "MatWeb"),
    ("Nylon 6 PA6",             "Polymer",    2.7, 0.39, 1140, 90.0,  0.25,1600,   60,   75, "MatWeb"),
    ("ABS",                     "Polymer",    2.3, 0.35, 1050, 90.0,  0.17,1400,   40,   50, "MatWeb"),
    ("PTFE Teflon",             "Polymer",    0.5, 0.46, 2200,135.0,  0.25,1000,   14,   31, "MatWeb"),
    ("Epoxy Resin",             "Polymer",    3.5, 0.38, 1250, 55.0,  0.17,1100,   60,   70, "MatWeb"),
    ("CFRP isotropic approx",   "Composite", 70.0, 0.10, 1600,  2.0,   5.0, 750,  500,  600, "Approx"),
    ("GFRP isotropic approx",   "Composite", 25.0, 0.25, 1900, 11.0,   0.3, 800,  150,  200, "Approx"),
    ("Concrete structural",     "Concrete",  30.0, 0.20, 2400, 12.0,   1.8, 880,    0,   30, "ACI 318"),
    ("Silicon",                 "Semi",     130.0, 0.28, 2329,  2.6, 148.0, 700, 7000, 7000, "MatWeb"),
    ("Tungsten",                "Metal",    411.0, 0.28,19300,  4.5, 173.0, 134, 1500, 1725, "MatWeb"),
    ("Tool Steel H13",          "Steel",    215.0, 0.30, 7750, 11.3,  24.0, 460, 1000, 1200, "MatWeb"),
    ("Steel high-temp 500C",    "Steel",    170.0, 0.30, 7850, 12.0,  40.0, 600,  100,  200, "EN 1993-1-2"),
    ("Bronze C63000",           "Copper",   117.0, 0.34, 7580, 18.0,  50.0, 376,  345,  655, "MatWeb"),
    ("Aluminum 1100-H14",       "Aluminum",  68.9, 0.33, 2710, 23.6, 222.0, 904,  115,  125, "ASM"),
    ("Lead",                    "Metal",     16.0, 0.44,11340, 29.0,  35.0, 128,   12,   17, "MatWeb"),
]


class MaterialDatabase:

    def __init__(self, db_path: str = str(DEFAULT_DB)):
        self._path = db_path

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def search(self, query: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM materials WHERE LOWER(name) LIKE ? ORDER BY name",
                (f"%{query.lower()}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, material_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM materials WHERE id = ?", (material_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def seed(db_path: str = str(DEFAULT_DB)) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT NOT NULL,
            E_GPa REAL NOT NULL, nu REAL NOT NULL, rho_kgm3 REAL NOT NULL,
            alpha_1e6K REAL, k_WmK REAL, Cp_JkgK REAL,
            yield_MPa REAL, UTS_MPa REAL, source TEXT)""")
        conn.execute("DELETE FROM materials")
        conn.executemany(
            "INSERT INTO materials (name,category,E_GPa,nu,rho_kgm3,alpha_1e6K,"
            "k_WmK,Cp_JkgK,yield_MPa,UTS_MPa,source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            SEED_DATA,
        )
        conn.commit()
        conn.close()
