def get_click_pesa_fee(amount):
    if 500 <= amount <= 999:
        return 54
    if 1000 <= amount <= 1999:
        return 92
    if 2000 <= amount <= 2999:
        return 124
    if 3000 <= amount <= 3999:
        return 230
    if 4000 <= amount <= 4999:
        return 380
    if 5000 <= amount <= 9999:
        return 580
    if 10000 <= amount <= 19999:
        return 920
    if 20000 <= amount <= 39999:
        return 1150
    if 40000 <= amount <= 49999:
        return 1572
    if 50000 <= amount <= 99999:
        return 2136
    if 100000 <= amount <= 199999:
        return 3240
    if 200000 <= amount <= 299999:
        return 3660
    if 300000 <= amount <= 399999:
        return 4080
    if 400000 <= amount <= 499999:
        return 4340
    if 500000 <= amount <= 599999:
        return 4820
    if 600000 <= amount <= 799999:
        return 5230
    if 800000 <= amount <= 999999:
        return 6146
    if 1000000 <= amount <= 1999999:
        return 7210
    if 2000000 <= amount <= 3000000:
        return 7960

    return 0

