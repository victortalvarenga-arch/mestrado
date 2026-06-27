# Spatial distribution of the racks in the room

Reduced Dragonfly topology for stress testing.

This version keeps multiple groups and racks while reducing the number of compute nodes.

Inside a given rack the IDs of the nodes also define the position of the nodes on the Z axis, with nodes with smaller IDs being below the ones with bigger IDs.

|Rack|X|Y|Nodes (identifiers)|
|----|-|-|-------------------|
0|21|2|0, 1, 2, 3, 4, 5, 6, 7, 8, 9
1|20|2|10, 11, 12, 13, 14, 15, 16, 17, 18, 19
2|19|2|20, 21, 22, 23, 24, 25, 26, 27, 28, 29
3|21|6|30, 31, 32, 33, 34, 35, 36, 37, 38, 39
4|20|6|40, 41, 42, 43, 44, 45, 46, 47, 48, 49
5|19|6|50, 51, 52, 53, 54, 55, 56, 57, 58, 59
6|21|10|60, 61, 62, 63, 64, 65, 66, 67, 68, 69
7|20|10|70, 71, 72, 73, 74, 75, 76, 77, 78, 79
8|19|10|80, 81, 82, 83, 84, 85, 86, 87, 88, 89
