# topo2osm-sweden
Convert Lantmäteriet topography data into files for OpenStreetMap.

### Usage ###

Usage: <code>python3 topo2osm.py \<municipality\> [\<category\>] [-options]</code>

Paramters:
* *municipality* - Name of municipality or 4 digit municipality number.
* *category* - Optional, one of the following data categories (themes) in the topography datasets:
  * <code>Anläggningsområde</code> - Landuses for industry, leisure and public usage. Useful for airports and sport pitches/tracks.
  * <code>Byggnadsverk</code> - Special buildings/structures such as communication masts, towers, chimneys etc. Use [building2osm](https://github.com/NKAmapper/building2osm-sweden/) to get buildings with better data.
  * <code>Hydro</code> / <code>Hydrografi</code> - Waterways. Used in the <code>Topo</code> (default) category.
  * <code>Höjd</code> - Mountains/peaks.
  * <code>Kommunikation</code> - Hiking related features such as routes and snowmobile trails. Use [nvdb2osm](https://github.com/atorger/nvdb2osm/) to get highways with better data.
  * <code>Kulturhistorisk lämning</code> - Heritage and archeological sites. Only provided with raw geojson output. Not provided for Topography 10.
  * <code>Ledningar</code> - Power lines and transformer station areas.
  * <code>Mark</code> - Land cover features such as wood, wetland, farmland and industrial/residential areas.
  * <code>Naturvård</code> - National parks, nature reserves and other protected areas.  Use [reserve2osm](https://github.com/NKAmapper/reserve2osm/) to get protected areas with better data (to be extended for Sweden).
  * If no category is provided, a combination of <code>Mark</code> and <code>Hydrogrfi</code> will be produced, including place names (also called category <code>Topo</code>).
* *options*:
  * <code>-seanames</code> - Include place names in the sea, such as bays, straits etc.
  * <code>-baynames</code> - Include place names which are parts of lakes and rivers, such as bays, straits, still water etc.
  * <code>-wetland</code> - Try to merge boundaries of wetland with wood and other topological features. 
  * <code>-nosimplify</code> - Do not simplify or concatenate geometry lines before output. 
  * <code>-geojson</code> - Output raw topo source data in geojson file.

### Requirements ###

  * Requires [GeoPandas](https://geopandas.org/en/stable/) library.
  * Required to download [Topography 10](https://geotorget.lantmateriet.se/geodataprodukter/topografi-10-nedladdning-vektor/) (or Topo 50, 100, 250) files downloaded from [Lantmäteriet Geotorget](https://geotorget.lantmateriet.se/) (minimum the file corresponding to the selected category above, usually *Mark* and *Hydro(grafi)*).
  * Required to download [Municipality boundaries](https://geotorget.lantmateriet.se/geodataprodukter/kommun-lan-rike-nedladdning-api/) downloaded from [Lantmäteriet Geotorget](https://geotorget.lantmateriet.se/).
  * Recommended to download the file [ortnamn_sverige_multipoint.geojson](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134/list/ortnamn%20sverige/ortnamn_Sverige_multipoint.geojson)) to get names on lakes, wetland, islands and rivers.
  * Recommended to download the Hydrografi files for [Topography 100](https://geotorget.lantmateriet.se/geodataprodukter/topografi-100-nedladdning-vektor/) and for [Topography 250](https://geotorget.lantmateriet.se/geodataprodukter/topografi-250-nedladdning-vektor/) to get meaningful *waterway=river* tagging.

### Notes ###

* The topo data is loaded from Lantmäteriet's Geotorget service. The data is free, but you need to apply for each dataset. Remember to say that you intend to use it for OpenStreetMap.
* The dataset *Topografi 10* is supported, as well as Topografi 50, 100 and 250.
* OSM relations are automatically created based on polygons and segment lines in the dataset. Note that wetland is in general not connected to other features. This will result in overlapping ways and nodes from wetland.
* Place names are derived from the dataset *Ortnamn* at Lantmäteriet, combined with coordinates used by each Topografi datasets. A few category corrections are made.
* River centerlines for *waterway=river* in *water=river* polygons are missing, but will hopefully be available if permission to use the *Hydrografi* dataset is obtained from Lantmätriet. 
* Parts of he program has exponential complexity. Most municipalities will run in a few seconds, large municipalities will run in minutes, while the largest municipalities might require more than an hour to complete.
* A few *FIXME=** tags are produced for place names whenever there are more than one name for an feature. Overlapping names are sorted by appearence in the various topo maps by Lantmäteriet (Topografi 250 with highest rank, then 100 etc).
* See example files at [Topo Sverige](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134/list/topo%20sverige) on Jottacloud.

### Changelog

* 0.3: Initial Beta version. A few minor improvements to be done.

### References ###

* [Topografi 10 content description](https://geotorget.lantmateriet.se/dokumentation/GEODOK/51/latest.html) at Lantmäteriet Geotorget.
* [Geotorget](https://geotorget.lantmateriet.se/) at Lantmäteriet.
* [Example files](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134/list/topo%20sverige) on Jottacloud.
* [building2osm](https://github.com/NKAmapper/building2osm-sweden/) on GitHub - Produces OSM files with buildings.
* [nvdb2osm](https://github.com/atorger/nvdb2osm/) on GitHub - Produces OSM files with highways.
* [reserve2osm](https://github.com/NKAmapper/reserve2osm/) on GitHub - Produces OSM files with protected areas.
* [n50osm](https://github.com/NKAmapper/n50osm/) on GitHub - Similar program for N50 in Norway.
