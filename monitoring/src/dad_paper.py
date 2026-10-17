"""Số liệu lấy từ bài báo gốc của DAD.

L. Vigoya, D. Fernandez, V. Carneiro, F. Cacheda, Annotated Dataset for Anomaly Detection in a Data Center
with IoT Sensors, Sensors 2020, 20(13), 3745. https://pmc.ncbi.nlm.nih.gov/articles/PMC7374380/

Đã đối chiếu đủ 16 dòng × 5 cột của Table 1 ("Statistical information", mục 3.2) với bản trên PMC.
"""
from __future__ import annotations

# Tên đầy đủ theo bài báo (mục 3.1); chữ số vị trí trong clientId suy ra từ giá trị đo (notebook BAO_CAO_PHAN_TICH_DAD, mục “Từ điển định danh”)
SENSOR_INFO = {
    "TFEU": ("Unit Entering Fluid Temperature", "nước lạnh đi vào tủ", 1),
    "TFSU": ("Unit Leaving Fluid Temperature", "nước đi ra khỏi tủ", 2),
    "TAS": ("Unit Supply Air Temperature", "khí cấp ra lối lạnh", 3),
    "TAR": ("Unit Return Air Temperature", "khí hồi từ lối nóng", 4),
}

# Table 1: 14 ngày đo thật, (mean, sd, min, max, median) theo (InRow, cảm biến)
REAL_TABLE1 = {
    (13, "TAS"): (20.00, .38, 18.2, 20.9, 19.9), (13, "TAR"): (27.33, .24, 26.1, 28.1, 27.3),
    (13, "TFEU"): (11.94, .93, 9.4, 14.3, 11.8), (13, "TFSU"): (15.89, .79, 13.9, 17.8, 15.8),
    (15, "TAS"): (20.00, .42, 18.0, 21.2, 19.9), (15, "TAR"): (27.20, .25, 25.1, 27.9, 27.2),
    (15, "TFEU"): (11.69, .98, 9.1, 14.2, 11.6), (15, "TFSU"): (15.37, .89, 13.2, 17.8, 15.2),
    (23, "TAS"): (20.00, .34, 18.3, 20.8, 20.0), (23, "TAR"): (26.29, .27, 25.2, 27.3, 26.3),
    (23, "TFEU"): (11.14, 1.00, 8.1, 13.6, 11.0), (23, "TFSU"): (14.95, .88, 12.8, 17.4, 14.8),
    (25, "TAS"): (20.00, .37, 17.9, 21.1, 20.1), (25, "TAR"): (26.79, .22, 25.7, 27.6, 26.8),
    (25, "TFEU"): (11.24, 1.00, 8.5, 13.9, 11.1), (25, "TFSU"): (15.34, .88, 13.2, 17.7, 15.2),
}
