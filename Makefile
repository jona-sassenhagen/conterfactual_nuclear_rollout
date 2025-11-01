PYTHON ?= python3
DATA_FILE := data/scenario_data.json
SITE_DATA_FILE := docs/data/scenario_data.json
ASSETS := pro_nuclear.png anti_nuclear.png nuclear_plant.svg fossil_plant.png
SITE_ASSETS := $(ASSETS:%=docs/assets/%)

.PHONY: all data serve clean prepare assets

all: data

# Build or refresh the counterfactual + historical dataset
$(DATA_FILE): scripts/build_counterfactual.py \
	germany_power_plants_1990_complete.csv \
	fossil_construction_1990_2025_bnetza.csv \
	electricity-production-by-source.csv
	@$(PYTHON) scripts/build_counterfactual.py

data: $(DATA_FILE)

$(SITE_DATA_FILE): $(DATA_FILE)
	@mkdir -p $(dir $@)
	@cp $(DATA_FILE) $@

docs/assets/%: %
	@mkdir -p $(dir $@)
	@cp $< $@

assets: $(SITE_ASSETS)

prepare: data $(SITE_DATA_FILE) assets

# Launch a lightweight development server on port 5173
serve: prepare
	@echo "Serving docs/ on http://localhost:5173"
	@$(PYTHON) -m http.server 5173 --directory docs

clean:
	rm -f $(DATA_FILE) $(SITE_DATA_FILE)
