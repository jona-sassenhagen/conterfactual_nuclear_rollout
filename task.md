I want to model a scenario where Germany keeps building nuclear power plants after the 80s, and closes fossil fuel plants.

I have here a table of all German power stations, including commission and end date: germany_power_plants_1990_complete.csv

I want to show a scenario where:
- builds a new table of a nuclear roll-out
- continuously builds new plants so that one fictional new plant opens in 1990 (or two), at a rate comparable to the 80s (~1.5 per year)
- strictly avoids building any new fossil fuel plants
- closes fossil fuels plants as it becomes feasible (capacity equalized)
- finds suitable new sites for new plants: either adding power to existing nuclear plants, or reusing existing fossil sites of similar location

Do you get the problem?

So we want to simulate:

- date (multiple rows per year possible)
- site (either existing nuclear site, or reusing a fossil fuel plant site)
- name (running count per site)
- MW added
- running total nuclear
- running total fossil
- running total all in all
- fossil fuel sites closed (make sure to close fossil fuel sites actually running in that year - prefer older sites - avoid closing cogeneration and heating sites)
- fossil capacity closed
- total annual generation capabilities

And we want to compare it to the counterfactual scenario we actually got, with little fossil shutdown, even fossil build-out. See the file fossil_construction_1990_2025_bnetza.csv for historical build-out.

I also have a file of annual energy generation by source: twh_by_source.csv

I want to visualise this as an animated web app showing carbon emissions and clean energy availability over time.

On the right, the historical scenario, on the right, the counterfactual nuclear build-out scenario. Show lines growing on both sides. List plant construction and closures (on one side, fossil plant construction; on the other, hypotehtical nuclear power plant construction and fossil plant closures).

I also gave you images, fossil_plant and nuclear_plant for you to use.

