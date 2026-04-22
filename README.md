# DST5 KiCad Library

Custom KiCad symbol and footprint library.

## Contents
- `symbols/Aidan_DST_symbols.kicad_sym` – symbol library  
- `footprints/Aidan_DST_footprints.pretty` – footprint library  
- `3dmodels/` – optional 3D models  

## Setup

### Symbols
Schematic Editor → Preferences → Manage Symbol Libraries → Add existing  
Select: `./symbols/Aidan_DST_symbols.kicad_sym`

### Footprints
PCB Editor → Preferences → Manage Footprint Libraries → Add existing  
Select: `./footprints/Aidan_DST_footprints.pretty`

### (Optional) 3D Models
Preferences → Configure Paths → add:
- `DST_LIB = <path to this repo>`

Ensure footprints reference models via:
- `${DST_LIB}/3dmodels/...`
