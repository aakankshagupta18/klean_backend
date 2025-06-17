
def filter_unknown_chemicals(input_chemicals, known_names, known):
    tknown = []
    unknown = []

    for chem in input_chemicals:
        chem_lower = chem.lower()
        if any(chem_lower in known_name or known_name in chem_lower for known_name in known_names):
            tknown.append(chem)
        else:
            unknown.append(chem)

    return known, unknown