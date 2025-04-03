#!/usr/bin/env python3
# -*- coding: utf8


import urllib.request, urllib.parse, urllib.error
import zipfile
import json
import csv
import copy
import sys
import os
import time
import math
import io
import base64
from xml.etree import ElementTree as ET
from geopandas import gpd
import warnings

warnings.filterwarnings(
    action="ignore",
    message=".*has GPKG application_id, but non conformant file extension.*"
)


version = "0.4.0"

header = {"User-Agent": "nkamapper/topo2osm"}  # Header for other datasets than LM

topo_product = "Topo10"

topo_folder =       "~/Jottacloud/LM/"					# Folders containing national topo data files (subfolders Topo10, Topo50 etc.)
place_name_folder = "~/Jottacloud/osm/ortnamn sverige/"	# Folder containing import SSR files (default folder tried first)

precision = 7	 			# Decimals in coordinate output
island_size = 100000  	 	# Minimum square meters for place=island vs place=islet
simplify_factor = 0.2    	# Threshold for simplification
max_combine_members = 10 	# Maximum members for a wood feature to be combined
grid_size = 10000 			# 10x10 km (for Topo10, 50, 100)

debug =            False	# Include debug tags and unused segments
topo_tags =        False	# Include property tags from Topo10 in output
json_output =      False	# Output complete and unprocessed geometry in geojson format
get_name =         True 	# Use ortnamn2osm place names
get_hydrografi =   False 	# Load LM lake and river data
get_topo_rivers =  True 	# Use T100 and T50 topo data to determine rivers vs streams
load_landcover =   False 	# Load clipped municipality file from LM for "mark" layers (Marktäcke Nedladdning)
merge_node =       True 	# Merge common nodes at intersections
merge_grid =       True 	# Merge polygons across grids
merge_wetland =    False	# Merge wetland segments with "gräns" type segments
simplify =         True 	# Simplify geometry lines
add_sea_names =    False 	# Add sea, bay and strait names in ocean, not only in lakes
add_bay_names =    False 	# Add bay and strait names, both inland and in oceans (latter if add_sea_names is True)

token_filename = "geotorget_token.txt"	# Stored Geotorget credentials
token_folder = "~/downloads/"			# Folder where token is stored, if not in current folder

language_codes = {
	'SV': 'sv', 	# Svenska
	'TF': 'fit',	# Meänkieli (tornedalsfinska)
	'FI': 'fi',		# Finska
	'NS': 'se',		# Nordsamiska
	'LS': 'smj',	# Lulesamiska
	'US': 'sju',	# Umesamiska
	'SS': 'sma'		# Sydsamiska
}

data_categories = [ # Available topo datasets
	"anlaggningsomrade", "byggnadsverk", "hojd", "hydro", "kommunikation", "ledningar", "mark", "militartomrade",
	"naturvard", "norrapolcirkeln", "text", "topo"]  # "topo" will combine mark and hydro

avoid_objects = [  # Object types to exclude from output
	'Öppen mark', 'Fjällbjörkskog', 'Kalfjäll', 'Ej karterat område', 'Begränsningslinje, ej karterat område',  # Mark
	'Berg i dagen', 'Blockig mark', 'Tät vegetation, svårframkomlig',  # Mark Topo 50+
	'Strömriktningspil, liten', 'Strömriktningspil, stor', 'Bränning', 'Övervattensten',   # Hydro
	'Höjdkurva5', 'Gropkurva5'  # Höjd
]

auxiliary_objects = [ # Area delimiter objects
	'Bebyggelseområdesgräns', 'Industri- och handelsbebyggelsegräns', 'Odlingsmarksgräns', 'Skogsmarksgräns',
	'Strandlinje, sjö', 'Strandlinje, anlagt vatten', 'Strandlinje, vattendragsyta', 'Strandlinje, hav',
	'Stängning', 'Stängning mot hav', 'Öppen markgräns',
	'Gridline'
]

avoid_tags = [  # Topo properties to exclude from output (unless debug)
	'oppdateringsdato', 'datafangstdato',
	'målemetode', 'nøyaktighet'
]

object_sorting_order = [  # High priority will ensure ways in same direction
	'Hav', 'Sjö', 'Anlagt vatten', 'Vattendragsyta', 'Glaciär',
	'Industri- och handelsbebyggelse', 'Sluten bebyggelse', 'Hög bebyggelse', 'Låg bebyggelse', 'Bebyggelse', 'Torg',
	'Åker', 'Fruktodling',
	'Sankmark, våt', 'Sankmark, fast', 'Sankmark', 'Lövskog', 'Fjällbjörkskog', 'Barr- och blandskog', 'Skog'
]

segment_sorting_order = [  # High priority will ensure longer ways
	'Strandlinje, hav', 'Stängning mot hav', 'Strandlinje, sjö', 'Strandlinje, anlagt vatten', 'Stängning', 'Strandlinje, vattendragsyta',
	'Sankmark gräns', 'Industri- och handelsbebyggelsegräns', 'Bebyggelseområdesgräns', 'Odlingsmarksgräns', 'Skogsmarksgräns', 'Öppen markgräns',
	'Gridline'
]


# Default OSM tagging per object type

osm_tags = {

	# Mark

	'Sluten bebyggelse':					{ 'landuse': 'retail' },
	'Hög bebyggelse':						{ 'landuse': 'residential' },
	'Låg bebyggelse':						{ 'landuse': 'residential' },
	'Bebyggelse':							{ 'landuse': 'residential' },  # Topo 100, 250
	'Industri- och handelsbebyggelse':		{ 'landuse': 'industrial' },
	'Åker':									{ 'landuse': 'farmland' },
	'Fruktodling':							{ 'landuse': 'orchard' },
#	'Kalfjäll':								{ 'natural': 'bare_rock' },
	'Torg':									{ 'place': 'square' },
	'Barr- och blandskog':					{ 'natural': 'wood' },
	'Lövskog':								{ 'landuse': 'forest', 'leaf_type': 'broadleaved' },
	'Skog':									{ 'natural': 'wood' },  # Topo 100, 250
#	'Fjällbjörkskog':						{ 'natural': 'scrub' },
	'Strandlinje, hav':						{ 'natural': 'coastline' },
	'Stängning mot hav':					{ 'natural': 'coastline' },
	'Sjö':									{ 'natural': 'water' },
	'Vattendragsyta':						{ 'natural': 'water', 'water': 'river' },
	'Anlagt vatten':						{ 'natural': 'water', 'water': 'pond' },
	'Glaciär':								{ 'natural': 'glacier' },
	'Sankmark, fast':						{ 'natural': 'wetland', 'wetland': 'bog' },
	'Sankmark, våt':						{ 'natural': 'wetland', 'wetland': 'marsh' },
	'Sankmark':								{ 'natural': 'wetland' },  # Topo 250

	# Hydro

	'Vattendrag':							{ 'waterway': 'stream' },
	'Fors':									{ 'waterway': 'rapids' },
	'Vattenfall':							{ 'waterway': 'waterfall' },
	'Dammbyggnad':							{ 'waterway': 'dam' },
	'Dammbyggnad, punkt':					{ 'waterway': 'dam' },
	'Brygga':								{ 'man_made': 'pier' },
	'Pir':									{ 'man_made': 'breakwater' },
	'Kaj':									{ 'man_made': 'quay' },
	'Avbärare':								{ 'seamark:type': 'shoreline_construction', 'seamark:shoreline_construction:category': 'groyne' },
	'Ledverk':								{ 'seamark:type': 'shoreline_construction', 'seamark:shoreline_construction:category': 'fender' },
	'Dykdalb':								{ 'seamark:type': 'mooring', 'seamark:mooring:category': 'dolphin', 'mooring': 'yes' },
	'Dykdalb, mindre':						{ 'seamark:type': 'mooring', 'seamark:mooring:category': 'pile', 'mooring': 'yes' },
	'Vattentub/vattenränna':				{ 'man_made': 'pipeline', 'substance': 'water' },
	'Akvedukt':								{ 'waterway': 'canal', 'bridge': 'aqueduct', 'layer': '1' },
	'Slussport':							{ 'waterway': 'sluice_gate' },
#	'Bränning':								{ 'seamark:type': 'rock', 'seamark:rock:water_level': 'awash' },
#	'Övervattensten':						{ 'seamark:type': 'rock', 'seamark:rock:water_level': 'always_dry' },

	# Anläggningsområde

	'Industriområde':						{ 'landuse': 'industrial' },
	'Samhällsfunktion':						{},
	'Rekreation':							{ 'landuse': 'recreation_ground' },
	'Civilt skjutfält':						{ 'leisure': 'shooting_ground' },
	'Idrottsplan':							{ 'leisure': 'pitch' },
	'Start- och landningsbana':				{ 'aeroway': 'runway'  },
	'Flygplatsområde':						{ 'aeroway': 'aerodrome' },
	'Helikopterplats':						{ 'aeroway': 'heliport' },
	'Industriområde, punkt':				{},
	'Idrettsområde, punkt':					{},
	'Samhällsfunksjon, punkt':				{},
	'Rekreation, punkt':					{},
	'Idrottsplan, punkt':					{},

	# Byggnadsverk

	'Renstängsel':							{ 'barrier': 'fence' },
	'Lintrafik':							{ 'aerialway': 'yes' },  # Unknown type
	'Skorsten':								{ 'man_made': 'chimney' },
	'Mast':									{ 'man_made': 'mast' },
	'Fyrbyggnad':							{ 'amenity': 'lighthouse' },
	'Klockstapel':							{ 'man_made': 'tower', 'tower:type': 'bell_tower' },
	'Kyrka':								{ 'amenity': 'place_of_worship', 'religion': 'christian', 'denomination': 'lutheran', 'building': 'church' }, 
	'Kåta':									{ 'building': 'hut' },
	'Raststuga':							{ 'amenity': 'shelter', 'shelter_type': 'basic_hut' },
	'Torn':									{ 'man_made': 'tower' },
	'Skyddsvärn':							{ 'amenity': 'shelter', 'shelter_type': 'bomb_shelter' },
	'Vindkraftverk':						{ 'power': 'generator', 'generator:source': 'wind', 'generator:method': 'wind_turbine', 'generator:type': 'horizontal_axis' },
	'Vindskydd':							{ 'amenity': 'shelter', 'shelter_type': 'lean_to' },
	'Väderkvarn':							{ 'man_made': 'windmill' },

	# Naturvård

	'Nationalpark':							{ 'boundary': 'national_park', 'protect_class': '2' },
	'Naturreservat':						{ 'leisure': 'nature_reserve', 'boundary': 'protected_area', 'protect_class': '1' },
	'Naturvårdsområde':						{ 'boundary': 'protected_area', 'protect_class': '6' },  # Local protection
	'Naturminnesområde':					{ 'boundary': 'protected_area', 'protect_class': '3' },
	'Djurskyddsområde':						{ 'boundary': 'protected_area', 'protect_class': '4' },
	'Kulturreservat':						{ 'boundary': 'protected_area', 'protect_class': '5' },
	'Naturminne':							{ 'tourism': 'attraction', 'protect_class': '3' },
	'Övrigt naturobjekt':					{ 'tourism': 'attraction' },
	'Eldningsförbud':						{ 'openfire': 'no' },
	'Tält- och eldningsförbud':				{ 'tents': 'no', 'openfire': 'no' },
	'Förbjudet område för terrängfordon':	{ 'motor_vehicle': 'no' },
	'Förbjudet område för terrängfordon, tidsbegränsat':	{ 'motor_vehicle': 'no' },

	# Höjd

	'Triangelpunkt':						{ 'natural': 'peak' },
	'Markhöjd':								{ 'natural': 'peak' },

	# Kommunikation

	'Gångstig':								{ 'highway': 'path' },
	'Elljusspår':							{ 'highway': 'path', 'lit': 'yes' },
	'Traktorväg':							{ 'highway': 'track' },
	'Vandringsled':							{ 'highway': 'path', 'trailblazed': 'yes' },
	'Vandrings- och vinterled':				{ 'highway': 'path', 'trailblazed': 'yes' },
	'Vad':									{ 'ford': 'yes' },
	'Hjälptelefon':							{ 'emergency': 'phone' },
	'Parkering':							{ 'amenity': 'parking', 'hiking': 'yes' },

	# Ledningar

	'Kraftledning stam':					{ 'power': 'line' },
	'Kraftledning region':					{ 'power': 'line' },
	'Kraftledning fördelning':				{ 'power': 'minor_line' },
	'Rörledning':							{ 'man_made': 'pipeline' },
	'Telefonledning':						{ 'telecom': 'line' },
	'Transformatorområde':					{ 'power': 'substation' },

	# Militärt område

	'Militärt övningsfält':					{ 'landuse': 'military', 'military': 'training_area' },
	'Militärt skjutfält':					{ 'landuse': 'military', 'military': 'range' },
	'Kasernområde':							{ 'landuse': 'military', 'military': 'base' }
}


# Tagging based on subtype/purpose

osm_tags_purpose = {

	# Industriområdesändamål

	'Energiproduktion':			{ 'landuse': 'industrial', 'power': 'plant' },
	'Gruvområde':				{ 'landuse': 'quarry' },
	'Rengärde':					{ 'barrier': 'fence' },  # For raindeer
	'Testbana':					{ 'leisure': 'sports_centre', 'sport': 'motor' },
	'Täkt':						{ 'landuse': 'quary' },
	'Hamn':						{ 'landuse': 'industrial', 'industrial': 'port' },

	# Samhällsfunktionsområdesändamål

	'Avfallsanläggning':		{ 'amenity': 'recycling', 'recycling_type': 'centre' },
	'Begravningsplats':			{ 'landuse': 'cemetery' },
	'Civilt övningsfält':		{ 'amenity': 'rescue_station' },
	'Kriminalvårdsanstalt':		{ 'amenity': 'prison' },
	'Sjukhusområde':			{ 'amenity': 'hospital' },
	'Skolområde':				{ 'amenity': 'school' },
	'Trafikövningsplats':		{ 'amenity': 'driving_school' },
	'Sjöräddningsstation':		{ 'emergency': 'water_rescue' },

	# Rekreationsändamål

	'Aktivitetspark':			{ 'leisure': 'playground' },
	'Badanläggning':			{ 'leisure': 'swimming_pool' },
	'Besökspark':				{ 'tourism': 'theme_park' },
	'Campingplats':				{ 'tourism': 'camp_site' },
	'Friidrottsanläggning':		{ 'leisure': 'sports_centre', 'sport': 'athletics' },
	'Golfbana':					{ 'leisure': 'golf_course' },
	'Hundsportanläggning':		{ 'leisure': 'dog_park' },
	'Hästsportanläggning':		{ 'leisure': 'pitch', 'sport': 'equestrian' },
	'Idrottsanläggning':		{ 'leisure': 'sports_centre' },
	'Koloniområde':				{ 'landuse': 'allotments' },
	'Kulturanläggning':			{ 'amenity': 'social_centre' },
	'Motorsportanläggning':		{ 'leisure': 'sports_centre', 'sport': 'motor' },
	'Parkområde':				{ 'leisure': 'park' },
	'Skjutbaneområde':			{ 'leisure': 'shooting_ground' },
	'Vintersportanläggning':	{ 'landuse': 'winter_sports' },
	'Badplats':					{ 'leisure': 'bathing_place' },
	'Gästhamn':					{ 'leisure': 'marina', 'seamark:type': 'harbour', 'seamark:harbour:category': 'marina' },
	'Småbåtshamn':				{ 'leisure': 'marina', 'seamark:type': 'harbour', 'seamark:harbour:category': 'marina_no_facilities' },
	'Ställplats':				{ 'tourism': 'caravan_site' },

	# Idrottsplansändamål

	'Bollplan':					{ 'leisure': 'pitch' },
	'Fotbollsplan':				{ 'leisure': 'pitch', 'sport': 'soccer' },
	'Galoppbana':				{ 'leisure': 'track', 'sport': 'horse_racing' },
	'Isbana':					{ 'leisure': 'ice_rink' },
	'Löparbana':				{ 'leisure': 'track', 'sport': 'running' },
	'Motorsportbana':			{ 'leisure': 'track', 'sport': 'motor' },
	'Tennisbana':				{ 'leisure': 'sport', 'sport': 'tennis' },
	'Travbana':					{ 'leisure': 'track', 'sport': 'horse_racing' },
	'Skjutbana':				{ 'landuse': 'shooting_ground' },
	'Skjutbana, mindre':		{ 'landuse': 'shooting_ground' }
}



# OSM tagging; first special cases

def tag_object(feature_type, geometry_type, properties, feature):

	tags = {}
	missing_tags = set()

	# First, special object cases with additional properties
	# Note: osm_tags dict not used in this section unless specifically applied per feature type

	if feature_type == "Vattendrag":
		if properties['kanal'] == "Ja":
			tags['waterway'] = "canal"
		elif properties['storleksklass'] > "Klass 1" or "Klass" not in properties['storleksklass'] and properties['storleksklass'] > "1":
			tags['waterway'] = "river"
		else:
			tags['waterway'] = "stream"
		if "vattendragsid" in properties:
			tags['VATTENDRAG'] = properties['vattendragsid']

	elif feature_type in ['Sjö', 'Anlagt vatten']:
		tags['natural'] = "water"
		if feature_type == "Anlagt vatten":
			tags['water'] = "pond"
		if "hojd_over_havet" in properties:
			if "-" in properties['hojd_over_havet']:
				ele_split = properties['hojd_over_havet'].split("-")
				tags['ele'] = ele_split[1]
				tags['ele:min'] = ele_split[0]
				tags['water'] = "reservoir"
			else:
				tags['ele'] = properties['hojd_over_havet']  # No decimals
		if "reglerat_vatten" in properties and properties['reglerat_vatten'] == "Ja":
			tags['water'] = "reservoir"
		if "vattenytaid" in properties:
			tags['ref:lantmateriet:vatten'] = properties['vattenytaid']

	elif feature_type in ['Industriområde', 'Idrettsområde', 'Samhällsfunktion', 'Rekreation', 'Idrottsplan',
				'Industriområde, punkt', 'Idrettsområde, punkt', 'Samhällsfunktion, punkt', 'Rekreation, punkt', 'Idrottsplan, punkt']:

		if "andamal" in properties and properties['andamal'] != "Ospecificerad":
			tags['OBJEKTTYP'] = feature_type + " " + properties['andamal']
			tags.update(osm_tags_purpose[ properties['andamal'] ])
		else:
			tags['OBJEKTTYP'] = feature_type
			tags.update(osm_tags[ feature_type ])

	elif feature_type == "Start- och landningsbana":
		tags['aeroway'] = "runway"
		if "flygplatsstatus" in properties and properties['flygplatsstatus'] == "Nedlagd":
			tags['note'] = "disused"

	elif feature_type == "Flygplatsområde":
		if "iata" in properties:
			tags['aeroway'] = "aerodrome"
			tags['iata'] = properties['iata']
		else:
			tags['aeroway'] = "airstrip"
		if "icao" in properties:
			tags['icao'] = properties['icao']

	elif feature_type == "Helikopterplats":
		if "iata" in properties:
			tags['aeroway'] = "heliport"
			tags['iata'] = properties['iata']
		else:
			tags['aeroway'] = "helipad"
		if "icao" in properties:
			tags['icao'] = properties['icao']

	elif feature_type in ['Nationalpark', 'Naturreservat', 'Naturvårdsområde', 'Djurskyddsområde', 'Kulturreservat',
							'Naturminne', 'Övrigt naturobjekt']:
		tags.update(osm_tags[ feature_type ])
		if "nvr_beskrivning" in properties:
			tags['name'] = properties['nvr_beskrivning'].strip()
			tags['short_name'] = properties['nvr_beskrivning'].strip()
			if tags['name'][-1] == "s":
				end = " "
			else:
				end = "s "
			if "djurskyddstyp" in properties and properties['djurskyddstyp']:
				tags['name'] += end + properties['djurskyddstyp'].lower()
			elif feature_type != "Övrigt naturobjekt":
				tags['name'] += end + feature_type.lower()
		if "nvid" in properties:
			tags['ref:naturvård'] = properties['nvid']
		if "ovrigt_naturobjektstyp" in properties:
			if properties['ovrigt_naturobjektstyp'] == "Grotta":
				tags['natural'] = "cave"
			elif properties['ovrigt_naturobjektstyp'] == "Källa":
				tags['natural'] = "spring"
			elif properties['ovrigt_naturobjektstyp'] == "Raukområde":
				tags['natural'] = "rock"

	elif "förbud" in feature_type or "Förbjudet" in feature_type:
		tags.update(osm_tags[ feature_type ])
		if "informativ_text" in properties:
			tags['description'] = properties['informativ_text'].strip()
			if "tidsbegransning" in properties:
				tags['description'] += " " + properties['tidsbegransning'].strip()

	elif feature_type in ["Gångstig", "Elljusspår", "Traktorväg", "Vandringsled", "Vandrings- och vinterled"]:
		tags.update(osm_tags[ feature_type ])
		if "skoterkorning_tillaten" in properties:
			if properties['skoterkorning_tillaten'] == "Ja":
				tags['scooter'] = "yes"
			elif properties['skoterkorning_tillaten'] == "Påbjuden":
				tags['scooter'] = "designated"
			elif properties['skoterkorning_tillaten'] == "Nej":
				tags['scooter'] = "no"
		if "vagutforande" in properties:
			if properties['vagutforande'] in ["Bro", "Sommarbro"]:
				tags['bridge'] = "yes"
				tags['layer'] = "1"
				if properties['vagutforande'] == "Sommarbro":
					tags['seasonal'] = "summer"
			elif properties['vagutforande'] in ["Tunnel", "Underfart"]:
				tags['tunnel'] = "yes"
				tags['layer'] = "-1"

	# Then, standard conversion dict

	elif feature_type in osm_tags:
		if osm_tags[ feature_type ]:  # Not empty
			tags.update( osm_tags[feature_type] )
		else:
			tags['FIXME'] = "Tag " + feature_type

	# General attributes

	if tags:
		if "hojdvarde" in properties:
			tags['ele'] = str(int(properties['hojdvarde']))

		if "hojd" in properties and properties['hojd'] > 0:
			tags['height'] = str(int(properties['hojd']))

	# Collect set of remaining object types not handled

	elif feature_type not in avoid_objects and feature_type not in auxiliary_objects and feature_type != "Hav":
		missing_tags.add(feature_type)

	return (tags, missing_tags)



# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()



# Format time

def timeformat (sec):

	if sec > 3600:
		return "%i:%02i:%02i hours" % (sec / 3600, (sec % 3600) / 60, sec % 60)
	elif sec > 60:
		return "%i:%02i minutes" % (sec / 60, sec % 60)
	else:
		return "%i seconds" % sec



# Calculate coordinate area of polygon in square meters
# Simple conversion to planar projection, works for small areas
# < 0: Clockwise
# > 0: Counter-clockwise
# = 0: Polygon not closed

def polygon_area (polygon):

	if polygon[0] == polygon[-1]:
		lat_dist = math.pi * 6371009.0 / 180.0

		coord = []
		for node in polygon:
			y = node[1] * lat_dist
			x = node[0] * lat_dist * math.cos(math.radians(node[1]))
			coord.append((x,y))

		area = 0.0
		for i in range(len(coord) - 1):
			area += (coord[i+1][1] - coord[i][1]) * (coord[i+1][0] + coord[i][0])  # (x2-x1)(y2+y1)

		return int(area / 2.0)
	else:
		return 0



# Calculate coordinate area of multipolygon, i.e. excluding inner polygons

def multipolygon_area (multipolygon):

	if type(multipolygon) is list and len(multipolygon) > 0 and type(multipolygon[0]) is list and \
			multipolygon[0][0] == multipolygon[0][-1]:

		area = polygon_area(multipolygon[0])
		for patch in multipolygon[1:]:
			inner_area = polygon_area(patch)
			if inner_area:
				area -= inner_area
			else:
				return None
		return area

	else:
		return None



# Calculate centroid of polygon
# Source: https://en.wikipedia.org/wiki/Centroid#Of_a_polygon

def polygon_centroid (polygon):

	if polygon[0] == polygon[-1]:
		x = 0
		y = 0
		det = 0

		for i in range(len(polygon) - 1):
			d = polygon[i][0] * polygon[i+1][1] - polygon[i+1][0] * polygon[i][1]
			det += d
			x += (polygon[i][0] + polygon[i+1][0]) * d  # (x1 + x2) (x1*y2 - x2*y1)
			y += (polygon[i][1] + polygon[i+1][1]) * d  # (y1 + y2) (x1*y2 - x2*y1)

		return (x / (3.0 * det), y / (3.0 * det) )

	else:
		return None



# Tests whether point (x,y) is inside a polygon
# Ray tracing method

def inside_polygon (point, polygon):

	if polygon[0] == polygon[-1]:
		x, y = point
		n = len(polygon)
		inside = False

		p1x, p1y = polygon[0]
		for i in range(n):
			p2x, p2y = polygon[i]
			if y > min(p1y, p2y):
				if y <= max(p1y, p2y):
					if x <= max(p1x, p2x):
						if p1y != p2y:
							xints = (y-p1y) * (p2x-p1x) / (p2y-p1y) + p1x
						if p1x == p2x or x <= xints:
							inside = not inside
			p1x, p1y = p2x, p2y

		return inside

	else:
		return None



# Test whether point (x,y) is inside a multipolygon, i.e. not inside inner polygons

def inside_multipolygon (point, multipolygon):

	if type(multipolygon) is list and len(multipolygon) > 0 and type(multipolygon[0]) is list and \
			multipolygon[0][0] == multipolygon[0][-1]:

		inside = inside_polygon(point, multipolygon[0])
		if inside:
			for patch in multipolygon[1:]:
				inside = (inside and not inside_polygon(point, patch))
				if not inside:
					break

		return inside

	else:
		return None



# Compute approximation of distance between two coordinates, (lon,lat), in meters.
# Works for short distances.

def point_distance (point1, point2):

	lon1, lat1, lon2, lat2 = map(math.radians, [point1[0], point1[1], point2[0], point2[1]])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return 6371000.0 * math.sqrt( x*x + y*y )  # Metres



# Compute closest distance from point p3 to line segment [s1, s2].
# Works for short distances.

def line_distance (s1, s2, p3, get_point=False):

	x1, y1, x2, y2, x3, y3 = map(math.radians, [s1[0], s1[1], s2[0], s2[1], p3[0], p3[1]])  # Note: (x,y)

	# Simplified reprojection of latitude
	x1 = x1 * math.cos( y1 )
	x2 = x2 * math.cos( y2 )
	x3 = x3 * math.cos( y3 )

	A = x3 - x1
	B = y3 - y1
	dx = x2 - x1
	dy = y2 - y1

	dot = (x3 - x1)*dx + (y3 - y1)*dy
	len_sq = dx*dx + dy*dy

	if len_sq != 0:  # in case of zero length line
		param = dot / len_sq
	else:
		param = -1

	if param < 0:
		x4 = x1
		y4 = y1
	elif param > 1:
		x4 = x2
		y4 = y2
	else:
		x4 = x1 + param * dx
		y4 = y1 + param * dy

	# Also compute distance from p to segment

	x = x4 - x3
	y = y4 - y3
	distance = 6371000 * math.sqrt( x*x + y*y )  # In meters

	if get_point:
		# Project back to longitude/latitude

		x4 = x4 / math.cos(y4)

		lon = math.degrees(x4)
		lat = math.degrees(y4)

		return (distance, (lon, lat))
	else:
		return distance



# Calculate shortest distance from node p to line.

def shortest_distance(p, line):

	d_min = 999999.9  # Dummy
	position = None
	for i in range(len(line) - 1):
		d = line_distance(line[i], line[i+1], p)
		if d < d_min:
			d_min = d
			position = i

	return (d_min, position)



# Calculate new node with given distance offset in meters
# Works over short distances

def coordinate_offset (node, distance):

	m = (math.pi / 180.0) * 6378137.0  # Meters per degree, ca 111 km

	latitude = node[1] + distance / m
	longitude = node[0] + distance / (m * math.cos( math.radians(node[1]) ))

	return (longitude, latitude)



# Calculate Hausdorff distance, including reverse.
# Abdel Aziz Taha and Allan Hanbury: "An Efficient Algorithm for Calculating the Exact Hausdorff Distance"
# https://publik.tuwien.ac.at/files/PubDat_247739.pdf
# Optional arguments:
# - 'limit' will break early if distance is above the limit (meters)
# - 'oneway' = True will only test p1 against p2, not the reverse
# - 'hits' = True will return list of index to nodes which were within given 'limit'

def hausdorff_distance (p1, p2, limit = False, oneway = False, hits = False):

	N1 = len(p1)  # Subtract 1 for circular polygons
	N2 = len(p2)

# Shuffling for small lists disabled
#	random.shuffle(p1)
#	random.shuffle(p2)

	h = []
	cmax = 0
	for i in range(N1):
		no_break = True
		cmin = 999999.9  # Dummy

		for j in range(N2 - 1):

			d = line_distance(p2[j], p2[j+1], p1[i])
    
			if d < cmax and not hits: 
				no_break = False
				break

			if d < cmin:
				cmin = d

		if cmin < 999999.9 and cmin > cmax and no_break:
			cmax = cmin
		if cmax > limit and limit and not hits:
			return cmax
		if cmin <= limit and hits:
			h.append(i)

	if oneway:
		return cmax
	if hits:
		return h

	for i in range(N2):
		no_break = True
		cmin = 999999.9  # Dummy

		for j in range(N1 - 1):

			d = line_distance(p1[j], p1[j+1], p2[i])
    
			if d < cmax:
				no_break = False
				break

			if d < cmin:
				cmin = d

		if cmin < 999999.9 and cmin > cmax and no_break:
			cmax = cmin
		if limit and cmax > limit:
			return cmax

	return cmax



# Simplify line, i.e. reduce nodes within epsilon distance.
# Ramer-Douglas-Peucker method: https://en.wikipedia.org/wiki/Ramer–Douglas–Peucker_algorithm

def simplify_line(line, epsilon):

	dmax = 0.0
	index = 0
	for i in range(1, len(line) - 1):
		d = line_distance(line[0], line[-1], line[i])
		if d > dmax:
			index = i
			dmax = d

	if dmax >= epsilon:
		new_line = simplify_line(line[:index+1], epsilon)[:-1] + simplify_line(line[index:], epsilon)
	else:
		new_line = [line[0], line[-1]]

	return new_line



# Identify bounds of line coordinates
# Returns lower left and upper right corners of square bounds + extra perimeter (in meters)

def get_bbox(coordinates, perimeter = 0):

	if isinstance(coordinates, tuple):
		patch = [ coordinates ]
	elif isinstance(coordinates[0], tuple):
		patch = coordinates
	else:
		patch = coordinates[0]
		
	min_node = list(patch[0])
	max_node = copy.deepcopy(min_node)

	for node in patch:
		for i in [0,1]:
			min_node[i] = min(min_node[i], node[i])
			max_node[i] = max(max_node[i], node[i])

	if perimeter > 0:
		min_node = coordinate_offset(min_node, - perimeter)
		max_node = coordinate_offset(max_node, + perimeter)

	return [ min_node, max_node ]



# Get total bbox for all features

def get_total_bbox():

	all_bbox = []
	for feature in features:
		all_bbox.extend([ get_bbox(feature['coordinates']) ])  # Build artificial coordinates of min/max

	return get_bbox(all_bbox)



# Determine overlap between bbox.
# Second argument, bbox2, may be a point or a bbox.

def bbox_overlap(bbox1, bbox2):

	if isinstance(bbox2, list):
		return (bbox1[0][0] <= bbox2[1][0] and bbox1[1][0] >= bbox2[0][0] and bbox1[0][1] <= bbox2[1][1] and bbox1[1][1] >= bbox2[0][1])
	else:
		return (bbox1[0][0] <= bbox2[0] <= bbox1[1][0] and bbox1[0][1] <= bbox2[1] <= bbox1[1][1])  # Point



# Create feature with one point

def create_point (node, tags, uuid = None, object_type = "Debug"):

	entry = {
		'object': object_type,
		'type': 'Point',
		'uuid': uuid,
		'coordinates': node,
		'members': [],
		'tags': {},
		'extras': {'objekttyp': object_type}
	}

	if isinstance(tags, str):
		entry['extras']['note'] = tags
	elif object_type == "Debug":
		entry['extras'].update(tags)
	else:
		entry['tags'].update(tags)

	if debug or object_type != "Debug":
		features.append(entry)




# Identify municipality name, unless more than one hit.
# Returns municipality number.

def get_municipality (parameter):

	# Load all municipalities

	url = "https://catalog.skl.se/rowstore/dataset/4c544014-8e8f-4832-ab8e-6e787d383752/json?_limit=400"
	try:
		file = urllib.request.urlopen(url)
	except urllib.error.HTTPError as e:
		sys.exit("\t*** Failed to load municiaplity names, HTTP error %i: %s\n\n" % (e.code, e.reason))
	data = json.load(file)
	file.close()

	municipalities = {}
	for municipality in data['results']:
		ref = municipality['kommunkod']
		if len(ref) < 4:
			ref = "0" + ref
		municipalities[ ref ] = municipality['kommun']

	# Identify chosen municipality

	if parameter.isdigit() and parameter in municipalities:
		return parameter, municipalities[ parameter ]
	else:
		found_ids = []
		for mun_id, mun_name in iter(municipalities.items()):
			if parameter.lower() == mun_name.lower():
				return mun_id, municipalities[ mun_id ]
			elif parameter.lower() in mun_name.lower():
				found_ids.append(mun_id)

		if len(found_ids) == 1:
			return found_ids[0], municipalities[ found_ids[0] ]
		elif not found_ids:
			sys.exit("*** Municipality '%s' not found\n\n" % parameter)
		else:
			mun_list = [ "%s %s" % (mun_id, municipalities[ mun_id ]) for mun_id in found_ids ]
			sys.exit("*** Multiple municipalities found for '%s' - please use full name:\n%s\n\n" % (parameter, ", ".join(mun_list)))



# Load municipality borders for filtering or clipping national data

def load_municipality_boundary(municipality_id):

	global municipality_boundary

	# Load boundary from LM

	header = { 'Authorization': 'Basic ' +  token }
	endpoint = "https://api-ver.lantmateriet.se/ogc-features/v1/administrativ-indelning/collections/kommuner/items"
	url = endpoint + "?crs=http://www.opengis.net/def/crs/EPSG/0/3006&f=json&&kommunkod=" + municipality_id

	request = urllib.request.Request(url, headers=header)
	try:
		file = urllib.request.urlopen(request)
	except urllib.error.HTTPError as err:
		message ("\t*** HTTP error %i: %s\n" % (err.code, err.reason))
		if err.code == 401:  # Unauthorized
			message ("\t*** Wrong username (email) or password, or you need approval for 'Kommun, län och rike, Direkt' at Geotorget\n\n")
			os.remove(token_filename)  # Enable reentry of username/password
			sys.exit()
		elif err.code == 403:  # Blocked
			sys.exit()
		else:
			sys.exit()


	data = json.load(file)
	file.close()

	# Keep only outer perimeter, disregarding inner rings

	multipolygon = data['features'][0]['geometry']['coordinates']
	if data['features'][0]['geometry'] == "Polygon":
		multipolygon = [ multipolygon ]

	new_multipolygon = []
	for polygon in multipolygon:
		new_polygon = [[ [ node[1], node[0] ] for node in polygon[0] ]]   # Keep outer ring only; swap x,y
		outside = True
		for outer_polygon in new_multipolygon:
			if inside_polygon(new_polygon[0][0], outer_polygon[0]):  # Exclude outer polygons which are inside inner polygons
				outside = False
				break
		if outside:
			new_multipolygon.append(new_polygon)

	data['features'][0]['geometry'] = {
		'type': 'MultiPolygon',
		'coordinates': new_multipolygon
	}

	municipality_boundary = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:3006")  # One feature only

	# Alternative loading from local file

#	filename = os.path.expanduser(topo_folder + "kommun-lan-rike_aktuell.gpkg")
#	if not os.path.isfile(filename):
#		sys.exit("\t*** File '%s' with municipality boundary not found\n\n" % filename)

#	borders = gpd.read_file(filename, layer="kommun")
#	municipality_boundary = borders[ borders["kommunkod"] == municipality_id ]



# Get stored Geotorget token or ask for credentials

def get_token():

	filename = token_filename

	if not os.path.isfile(filename):
		test_filename = os.path.expanduser(token_folder + filename)
		if os.path.isfile(test_filename):
			filename = test_filename

	if os.path.isfile(filename):		
		message ("Loading Geotorget credentials from file '%s'\n\n" % filename)
		file = open(filename)
		token = file.read()
		file.close()
	else:
		message ("Please provide Geotorget login (you need approval for 'Topografi 10 Nedladdning, vektor') ...\n")
		username = input("\tUser name: ")
		password = input("\tPassword:  ")
		token = username + ":" + password
		token = base64.b64encode(token.encode()).decode()
		file = open(filename, "w")
		file.write(token)
		file.close()
		message ("\tStoring credentials in file '%s'\n\n" % filename)

	return token



# Split patch if self-intersecting or touching polygon

def split_patch (coordinates):

	# Internal function for computing length based on coordinates (not in meters)

	def simple_length (coord):
		length = 0
		for i in range(len(coord) - 2):
			length += (coord[i+1][0] - coord[i][0])**2 + ((coord[i+1][1] - coord[i][1])**2) * 0.5
		return length


	# Start of main function

	for i in range(1, len(coordinates) - 1):
		first = coordinates.index(coordinates[i])
		if first < i:
			result1 = split_patch( coordinates[ : first ] + coordinates[ i: ] )
			result2 = split_patch( coordinates[ first : i + 1 ])
#			message ("\t*** SPLIT SELF-INTERSECTING/TOUCHING POLYGON: %s\n" % str(coordinates[i]))	
		
			if simple_length(result1[0]) > simple_length(result2[0]):
				result1.extend(result2)
				return result1
			else:
				result2.extend(result1)
				return result2

	return [ coordinates ]



def parse(coordinates):

	if isinstance(coordinates[0], float):
		return ( round(coordinates[0], precision), round(coordinates[1], precision) )
	else:
		patch = [ parse(patch) for patch in coordinates ]

		# Remove duplicate nodes after rounding
		if isinstance(patch[0], tuple):
			segment = []
			for node in patch:
				if not (segment and node == segment[-1]):
					segment.append(node)
			if len(segment) == 1 and len(patch) > 1:
				return []
			else:
				return segment
		else:
			return [ segment for segment in patch if segment ]  # Avoid empty segments



# Parse coordinates

def get_coordinates(feature):

	if isinstance(feature['geometry']['coordinates'][0], float):  # Point
		coordinates = parse(feature['geometry']['coordinates'])
		geometry_type = "Point"

	elif isinstance(feature['geometry']['coordinates'][0][0], float):  # LineString
		coordinates = parse(feature['geometry']['coordinates'])
		geometry_type = "LineString"

	elif isinstance(feature['geometry']['coordinates'][0][0][0], float):  # Polygon
		parse_coordinates = parse(feature['geometry']['coordinates'])
		coordinates = []
		for patch in parse_coordinates:
			coordinates.extend(split_patch(patch))  # Check for self-intersecting rings
		geometry_type = "Polygon"

	elif isinstance(feature['geometry']['coordinates'][0][0][0][0], float):  # Multipolygon (first polygon supported)
		parse_coordinates = parse(feature['geometry']['coordinates'][0])
		coordinates = []
		for polygon in parse_coordinates:
			polygon_coordinates = []
			for patch in polygon:
				polygon_coordinates.extend(split_patch(patch))  # Check for self-intersecting rings
			coordinates.append(polygon_coordinates)
		geometry_type == "Polygon"

	else:
		coordinates = []
		geometry_type = ""

	return geometry_type, coordinates



# Determine whether one of the grid nodes is at grid crossing 

def on_grid_cross(grid):

	for node in grid:
		if (abs(node[0] - round(node[0] / grid_size) * grid_size) < 0.0001
				and abs(node[1] - round(node[1] / grid_size) * grid_size) < 0.0001):
			return True
	return False



# Identify grid lines and create extra segments.
# First pass in 3006 projection.

def identify_grid_lines(topo_data):

	# Inner functions to determine whether two nodes are on (the same) grid line

	def on_grid(grid):

		for axis in [0, 1]:
			ok = True
			node1 = grid[0]
			if abs(node1[ axis ] - round(node1[ axis ] / grid_size) * grid_size) > 0.0001:
				ok = False
				continue
			for node2 in grid[1:]:
				if abs(node1[ axis ] - node2[ axis ]) > 0.0001:
					ok = False
					break
			if ok:
				return True

		return False


	# Start of main function.
	# Note: Geojson structure.

	grids = []
	for feature in topo_data.iterfeatures(na="drop", drop_id=True):
		if feature['properties']['objekttyp'] in object_sorting_order and feature['geometry']['type'] == "Polygon":

			coordinates = list(list(feature['geometry']['coordinates'])[0])[:-1]

			# First, roll coordinates until first node not on grid
			node1 = coordinates[-1]
			for node2 in coordinates[:]:
				if on_grid([ node1, node2 ]):
					coordinates.append(coordinates.pop(0))
					node1 = node2
				else:
					break

			# Build grid of consequtive nodes and save along the way
			grid = []
			for node in coordinates:
				if not grid:
					if on_grid([node ]):
						grid = [ node ]
				elif grid:
					if on_grid(grid + [ node ]):
						grid.append(node)
					else:
						if len(grid) > 1 and grid not in grids and list(reversed(grid)) not in grids:
							grids.append(grid)
						grid = []
						if on_grid([ node ]):
							grid = [ node ]

			if len(grid) > 1 and grid not in grids and list(reversed(grid)) not in grids:
				grids.append(grid)

	# Sort grids, longest first, to avoid problem with overlapping lines
	grids.sort(key=lambda line: abs(line[0][0] - line[-1][0]) + abs(line[0][1] - line[-1][1]), reverse=True)

	if grids:
		grid_features = []
		for i, grid in enumerate(grids):
			grid_feature = {
				'type': 'Feature',
				'properties': {
					'objekttyp': 'Gridline',
					'objektidentitet': "fiktiv-" + str(i + 10000)
				},
				'geometry': {
					'type': 'LineString',
					'coordinates': grid  #[ [ grid[0][0], grid[0][1] ], [ grid[1][0], grid[1][1] ] ]
				}
			}
			grid_features.append(grid_feature)

		gridlines = gpd.GeoDataFrame.from_features(grid_features, crs="EPSG:3006")
		topo_data = gpd.pd.concat([ topo_data, gridlines ])

	return topo_data



# Remove duplicates or ovrelapping lines.
# Second pass after conversion to WGS84 projection, which leads to rounding and more duplicates.

def remove_overlapping_grid_lines():

	# Inner function for sorting grid lines according to length

	def segment_length(segment):
		return point_distance(segment['coordinates'][0], segment['coordinates'][-1])


	# Inner function to remove duplicates

	def remove_grid_duplicates():

		grids = []
		for segment in segments[:]:
			if segment['object'] == "Gridline" and len(segment['coordinates']) == 2:
				if segment['coordinates'] in grids or list(reversed(segment['coordinates'])) in grids:
					segments.remove(segment)
				else:
					grids.append(segment['coordinates'])


	# Start of main function

	remove_grid_duplicates()

	grid_segments = [ segment for segment in segments if segment['object'] == "Gridline" and len(segment['coordinates']) > 2 ]

	for feature in features:
		if feature['object'] in object_sorting_order and feature['type'] == "Polygon":
			set_feature = set(feature['coordinates'][0])
			for segment in grid_segments:
				if set(segment['coordinates']) <= set_feature:
					set_segment = set(segment['coordinates'])

					# First, roll feature coordinates until first node is not on segment
					coordinates = feature['coordinates'][0][:-1]
					for node in coordinates[:]:
						if node in set_segment:
							coordinates.append(coordinates.pop(0))
						else:
							break

					# Then try building segment of consequtive nodes
					test_segment = []
					for node in coordinates:
						if node in set_segment:
							test_segment.append(node)
						else:
							if set(test_segment) == set_segment:
								break
							else:
								test_segment = []

					# If match, remove middle nodes from feature
					if set(test_segment) == set_segment:
						for node in segment['coordinates'][1:-1]:
							feature['coordinates'][0].remove(node)
							create_point(segment['coordinates'][1], "Removed grid point")  # Debug
						if feature['coordinates'][0][-1] in segment['coordinates'][1:-1]:
							feature['coordinates'][0][-1] = feature['coordinates'][0][0]  # Ensure circle

	# Remove middle nodes from grid segments
	for segment in grid_segments:
		segment['coordinates'] = [ segment['coordinates'][0], segment['coordinates'][-1] ]

	remove_grid_duplicates()

	count = sum(1 for segment in segments if segment['object'] == "Gridline")
	message ("\tCreated %i gridlines\n" % count)



# Load individual landcover layers from Läntmateriet

def load_topo_layers(data_category, topo_data):

	if data_category == "hydro" and topo_product != "Topo10":
		data_category = "hydrografi"

	if load_landcover and data_category == "mark" and topo_product == "Topo10":

		header = { 'Authorization': 'Basic ' +  token }
		url = "https://dl1.lantmateriet.se/mark/marktacke/marktacke_kn%s.zip" % municipality_id
		message ("\tLoading from URL: %s\n" % url)
		filename = "marktacke_kn%s.gpkg" % municipality_id
		request = urllib.request.Request(url, headers = header)

		try:
			file_in = urllib.request.urlopen(request)
		except urllib.error.HTTPError as err:
			message ("\t*** HTTP error %i: %s\n" % (err.code, err.reason))
			if err.code == 401:  # Unauthorized
				message ("\t*** Wrong username (email) or password, or you need approval for 'Marcktäcke Nedladdning, vektor' at Geotorget\n\n")
#				os.remove(token_filename)
				sys.exit()
			elif err.code == 403:  # Blocked
				sys.exit()
			else:
				return topo_data

		zip_file = zipfile.ZipFile(io.BytesIO(file_in.read()))
		file = zip_file.open(filename)

		layers = gpd.list_layers(file)

		for index, row in layers.iterrows():
			message ("\t\tLoading %s\n" % row['name'])
			data = gpd.read_file(file, layer=row['name'])
			data['versiongiltigfran'] = data['versiongiltigfran'].dt.strftime("%Y-%m-%d")  # Fix type
			topo_data = gpd.pd.concat([ topo_data, data ])

		file.close()
		zip_file.close()
		file_in.close()

	# Load latest topo file for municipality from Lantmäteriet

	else:
		filename = os.path.expanduser(topo_folder + topo_product + "/" + data_category + "_sverige.gpkg")
		message ("\tLoading from file: '%s'\n" % filename)
		if not os.path.isfile(filename):
			sys.exit("\t*** File '%s' not found - Please download from Geotorget\n\n" % filename)

		layers = gpd.list_layers(filename)

		for index, row in layers.iterrows():
			message ("\t\tLoading %s\n" % row['name'])
			data = gpd.read_file(filename, layer=row['name'])
			if data_category == "mark":
				data = data.clip(municipality_boundary, keep_geom_type=True, sort=True).explode()  # Clipping
			else:
				data = data[ data.geometry.intersects(municipality_boundary.geometry.union_all(method='unary')) ].explode()  # No clipping

			if hasattr(data, 'versiongiltigfran'):
				data['versiongiltigfran'] = data['versiongiltigfran'].dt.strftime("%Y-%m-%d")  # Fix type

			topo_data = gpd.pd.concat([ topo_data, data ])

	return topo_data



# Load Topo10 data from Lantmäteriet

def load_topo_data (municipality_id, municipality_name, data_category):

	global uuid, municipality_bbox

	lap = time.time()

	message ("Load topo data from Lantmäteriet...\n")

	source_date = {}
	object_count = {}
	missing_tags = set()
	topo_data = gpd.GeoDataFrame()

	# Load layers

	if data_category == "topo":
		topo_data = load_topo_layers("mark", topo_data)
		topo_data = load_topo_layers("hydro", topo_data)
#		topo_data = load_topo_layers("anlaggningsomrade", topo_data)
	else:
		topo_data = load_topo_layers(data_category, topo_data)

	if data_category in ["topo", "mark"]:  # and not save_geojson:
		topo_data = identify_grid_lines(topo_data)

	topo_data = topo_data.to_crs("EPSG:4326")

	# Loop features, parse and load into data structure and tag

	for feature in topo_data.iterfeatures(na="drop", drop_id=True):

		properties = feature['properties']

		if "objekttyp" not in properties:
			if "karttext" in properties:
				properties['objekttyp'] = "Höjdkurvstext"
			elif "regtext" in properties:
				properties['objekttyp'] ="Text"
			else:
				sys.exit("*** NO OBJECT TYPE: %s\n" % str(feature))

		feature_type = properties['objekttyp']

		if "objektidentitet" in properties:
			uuid = properties['objektidentitet']
		else:
			uuid = "Text"

		if feature_type not in object_count:
			object_count[ feature_type ] = 0
		object_count[ feature_type ] += 1

		# Dismiss certain objects

		if feature_type in avoid_objects and not json_output:
			continue

		geometry_type, coordinates = get_coordinates(feature)
		if not coordinates:
			continue

		# Ensure clockwise orientation of clipped polygons from LM

		if load_landcover and topo_product == "Topo10" and feature_type in object_sorting_order and polygon_area(coordinates[0]) > 0:
			for patch in coordinates:
				patch.reverse()

		# Convert waterfall to point

		if feature_type == "Vattenfall":
			coordinates = parse(( 0.5 * (coordinates[0][0] + coordinates[-1][0]), 0.5 * (coordinates[0][1] + coordinates[-1][1]) ))
			geometry_type = "Point"

		entry = {
			'object': feature_type,
			'type': geometry_type,
			'uuid': uuid,
			'coordinates': coordinates,
			'members': [],
			'tags': {},
			'extras': {}
		}

		# Store tags

		tags, new_missing_tags = tag_object(feature_type, geometry_type, properties, entry)
		entry['tags'].update(tags)
		for key, value in iter(properties.items()):
			entry['extras'][ key ] = str(value)
		missing_tags.update(new_missing_tags)

		if topo_tags and not debug:
			for key, value in iter(properties.items()):
				if key not in avoid_tags:
					entry['tags'][ "TOPO_" + key ] = value

		# Add to relevant list

		if not (geometry_type == "LineString" and len(entry['coordinates']) <= 1):
			if feature_type in auxiliary_objects:
				entry['used'] = 0
				segments.append(entry)
			elif entry['tags'] or debug or json_output or feature_type == "Hav":
				features.append(entry)
#			else:
#				message ("\t*** SEGMENT TOO SHORT: %s\n" % uuid)

		# Count source dates for information (10 year intervals)

		year = ""
		if "versiongiltigfran" in properties:
			year = properties['versiongiltigfran'][:4]  # [:3] + "0"
		if year > "1801":
			if year not in source_date:
				source_date[ year ] = 0
			source_date[ year ] += 1


	if not features:
		sys.exit("\nNo data found\n\n")

	if data_category in ["topo", "mark"]: # and not save_geojson:
		remove_overlapping_grid_lines()

	# Get bbox for municipality
	if features:
		municipality_bbox = [ coord for node in get_total_bbox() for coord in node ]  # Flatten 4 coordinates
		message ("\tBounding box: %s\n" % str(municipality_bbox))

	# Summary messages

	message("\tObjects loaded:\n")
	for object_type in sorted(object_count):
		if object_type not in auxiliary_objects:
			message("\t\t%i\t%s\n" % (object_count[object_type], object_type))

	if missing_tags:
		message ("\tNot tagged: %s\n" % (", ".join(missing_tags)))

	total = sum(source_date.values())
	if total > 0:
		message ("\tSource dates:\n")	
		for year in sorted(source_date.keys()):
			if round(100 * source_date[ year ] / total) > 0:
				message ("\t\t%s:\t%2i%%\n" % (year, round(100 * source_date[ year ] / total)))

	message ("\t%i feature objects, %i segments\n" % (len(features), len(segments)))
	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))



# Combine waterways into longer ways

def combine_rivers():

	# Selected all waterways

	topo_rivers = []
	for river in features:
		if river['object'] in ["Vattendrag"]:
			topo_rivers.append(river)

	# Combine rivers of same type and same network branch until exhausted

	count_combine = 0
	while topo_rivers:
		combination = topo_rivers.pop(0)
		count_segments = 1

		found = True
		while found and combination['coordinates'][0] != combination['coordinates'][-1]:
			found = False
			for river in topo_rivers[:]:
				if ("vattendragsid" in river['extras'] and river['extras']['vattendragsid'] == combination['extras']['vattendragsid']
						and river['tags']['waterway'] == river['tags']['waterway']
						and (("name" in river['tags']) == ("name" in combination['tags']))):  # Xor

					if river['coordinates'][0] == combination['coordinates'][-1]:
						combination['coordinates'] = combination['coordinates'] + river['coordinates'][1:]
						found = True
					elif river['coordinates'][-1] == combination['coordinates'][0]:
						combination['coordinates'] = river['coordinates'] + combination['coordinates'][1:]
						found = True

					if found:							
						topo_rivers.remove(river)
						features.remove(river)
						count_segments += 1
						break

			if count_segments > 1:
				count_combine += 1

	if count_combine > 0:
		message ("\t%i rivers combined\n" % count_combine)



# Load rivers from Topo50 and Topo100 to establish which waterways are rivers (not streams)

def load_topo_rivers():

	message ("Prepare rivers ...\n")

	rivers = set()

	for topo in ["Topo100", "Topo50"]:

		if topo == topo_product:
			for feature in features:
				if feature['object'] == "Vattendrag" and "storleksklass" in feature['extras'] and int(feature['extras']['storleksklass']) > 1:
					rivers.add(feature['extras']['vattendragsid'])

		else:
			filename = topo_folder + "%s/hydrografi_sverige.gpkg" % topo
#			message ("\tFile: '%s'\n" % filename)

			try:
				data = gpd.read_file(filename, layer="hydrolinje")
			except:
				message ("\t*** Failed to load file '%s'. Please download from Geotorget. Continues without waterway=river tag.\n" % filename)
				continue

			data = data[ data.geometry.intersects(municipality_boundary.geometry.union_all(method='unary')) ].explode()  # No clipping
			data['skapad'] = data['skapad'].dt.strftime("%Y-%m-%d")  # Fix type
			data = data.to_crs("EPSG:4326")

			# Build set of waterway id's which are rivers 

			for index, row in data.iterrows():
				if int(row['storleksklass']) > 1:
					rivers.add(row['vattendragsid'])

	# Tag as rivers

	for feature in features:
		if feature['object'] == "Vattendrag":
			if ("vattendragsid" in feature['extras'] and feature['extras']['vattendragsid'] in rivers
					and "waterway" in feature['tags'] and feature['tags']['waterway'] == "stream"):
				feature['tags']['waterway'] = "river"

	if not rivers:
		get_topo_rivers = False  # Try tagging rivers later based on place names

	message ("\tMatched %i waterways from Topo 50 and Topo 100\n" % len(rivers))



# Load waterways from Hydrografi dataset.
# Not currently used.

def load_hydrografi_rivers():

	message ("Load river data from Lantmäteriet ...\n")

	lap = time.time()
	hydro_river_count = 0
	limit = 1000
	more_data = True
	language_order = ["swe"] + list(language_codes.values())  # Used for sorting names
	rivers = {}

	collection = {
		'type': 'FeatureCollection',
		'features': []
	}

	# Paging results

	endpoint = "https://api.lantmateriet.se/ogc-features/v1/hydrografi/collections/WatercourseLine/items?"
	header = { 'Authorization': 'Basic ' +  token }

	while more_data:
		url = (endpoint + "bbox=%s&f=json&limit=%i&offset=%i"
							% (",".join(str(c) for c in municipality_bbox), limit, hydro_river_count))
		request = urllib.request.Request(url, headers=header)
		try:
			file = urllib.request.urlopen(request)
		except urllib.error.HTTPError as err:
			message("\t\t*** %s\n" % err)
			more_data = False
			continue

		data = json.load(file)
		file.close()

		for feature in data['features']:
			properties = feature['properties']
			river = {
				'id': feature['id'],
				'names': []
			}
			if "geographicalName" in properties:
				for name in properties['geographicalName']:
					river['names'].append({
						'name': name['text'],
						'language': name['language']
					})
				river['names'].sort(key=lambda name: language_order.index(name['language']))
			rivers[ properties['inspireId'] ] = river

		hydro_river_count += len(data['features'])
		message ("\r\t%i " % hydro_river_count)

		if data['numberReturned'] < limit:
			more_data = False

		collection['features'].extend(data['features'])

	message ("\r\tLoaded %i rivers\n" % hydro_river_count)
	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))

	file = open("test_rivers.geojson", "w")
	json.dump(collection, file, indent=1, ensure_ascii=False)
	file.close()



# Load lakes from Hydrografi dataset to get lake names.

def load_hydrografi_lakes():

	message ("\tLoading lake names ...\n")

	lap = time.time()
	topo_lake_count = 0
	hydro_lake_count = 0
	limit = 1
	more_data = True
	language_order = ["swe"] + list(language_codes.values())  # Used for sorting names
	lakes = {}

	endpoint = "https://api.lantmateriet.se/ogc-features/v1/hydrografi/collections/StandingWater/items?"
	header = { 'Authorization': 'Basic ' +  token }

	# Load lake by lake from API. This method is the quickest.

	if True:
		for feature in features:
			if "ref:lantmateriet:vatten" in feature['tags']:

				url = endpoint + "f=json&limit=10&offset=0&inspireId=" + feature['tags']['ref:lantmateriet:vatten']
				request = urllib.request.Request(url, headers=header)
				try:
					file = urllib.request.urlopen(request)
				except urllib.error.HTTPError as err:
					message("\t\t*** %s\n" % err)
					break

				data = json.load(file)
				file.close()
	
				if data['numberReturned'] > 0:
					lake_feature = data['features'][0]
					properties = lake_feature['properties']
					lake = {
						'id': lake_feature['id'],
						'area': properties['surfaceArea'],
#						'tidal': properties['tidal'] == "true",
						'names': []
					}
					if properties['elevation'] != "other:unpopulated":
						lake['ele'] = properties['elevation']
					if "geographicalName" in properties:
						for name in properties['geographicalName']:
							lake['names'].append({
								'name': name['text'],
								'language': name['language']
							})
					lake['names'].sort(key=lambda name: language_order.index(name['language']))
					lakes[ properties['inspireId'] ] = lake
					hydro_lake_count += 1
					message ("\r\t%i " % hydro_lake_count)

	# Alernative method: Load all rivers within bbox of municipality

	else:
		while more_data:
			url = (endpoint + "bbox=%s&f=json&filter=geographicalName.text%%20IS%%20NOT%%20NULL&limit=%i&offset=%i"
								% (",".join(str(c) for c in municipality_bbox), limit, hydro_lake_count))
			request = urllib.request.Request(url, headers=header)
			try:
				file = urllib.request.urlopen(request)
			except urllib.error.HTTPError as err:
				message("\t\t*** %s\n" % err)
				more_data = False
				continue

			data = json.load(file)
			file.close()

			for feature in data['features']:
				properties = feature['properties']
				lake = {
					'id': feature['id'],
					'area': properties['surfaceArea'],
	#				'tidal': properties['tidal'] == "true",
					'names': []
				}
				if properties['elevation'] != "other:unpopulated":
					lake['ele'] = properties['elevation']
				for name in properties['geographicalName']:
					lake['names'].append({
						'name': name['text'],
						'language': name['language']
					})
				lake['names'].sort(key=lambda name: language_order.index(name['language']))
				lakes[ properties['inspireId'] ] = lake

			hydro_lake_count += len(data['features'])
			message ("\r\t%i " % hydro_lake_count)

			if data['numberReturned'] < limit:
				more_data = False

	# Update lake info

	for feature in features:
		if "ref:lantmateriet:vatten" in feature['tags'] and feature['tags']['ref:lantmateriet:vatten'] in lakes:
			tags = feature['tags']
			lake = lakes[ tags['ref:lantmateriet:vatten'] ]

			names = []
			for name in lake['names']:
				if name['language'] == "swe":
					if len(lake['names']) == 1:
						key = "name"
					else:
						key = "name:sv"
				else:
					key = "name:" + name['language']
				tags[ key ] = name['name']
				if name['name'] not in names:
					names.append(name['name'])

			if names and "name" not in tags:
				tags['name'] = " - ".join(names)

			if "ele" in lake and "ele" not in feature['tags']:
				feature['tags']['ele'] = str(lake['ele'])  # No decimals
			if lake['area'] > 1000000 and "water" not in feature['tags']:  # 1 km2
				feature['tags']['water'] = "lake"
#			if lake['tidal']:
#				feature['tags']['tidal'] = "yes"
			feature['extras']['lm_area'] = str(int(lake['area']))  # Square meters

		if feature['object'] in ['Sjö', 'Anlagt vatten']:
			topo_lake_count += 1

	message ("\r\t%i Topo10 lakes matched against %i Hydrografi lakes\n" % (topo_lake_count, hydro_lake_count))
#	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))



# Load place names from ortnamn2osm file

def load_place_names():

	avoid_sea_names = [ # Many duplicates of these names in dataset
		'Bottenviken', 'Bottenhavet', 'Ålands hav', 'Östersjön', 'Öresund', 'Kattegatt', 'Skagerrak'  # Note: Östersjön used also for lakes
	]

	river_suffix = [ # River/stream name endings; used to fix incorrect place name type "Sjö" -> "Vattendrag"
		"bäcken", "älven", "ån",							# Svenska :sv
		"joki", "oja", "väylä",	"koski",					# Meänkieli (tornedalsfinska) :fit, Finska :fi
		"johka", "eatnu",  									# Nordsamiska :se
		"jåhkå", "jågåsj", "ädno", "guojkka", 				# Lulesamiska :smj
		"juhka", "juhkka", "juhkatje", "ädnuo", "ännuo",	# Umesamiska :sju
		"johke", "johkatje", "jeanoe"  						# Sydsamiska :sma
	]

	stillwater_suffix = [  # Fix place name type "Vattendrag" -> "Del av vatten"
		"selet", "savvun", "savoj", "suvvane", "sovvene", "soven", "hölet"
	]


	# Internal function to check match with name endings

	def name_match(tags, word_suffix):
		for key, value in iter(tags.items()):
			if "name" in key and any(word == value[ max(0, len(value) - len(word)) : ].lower() for word in word_suffix):
				return True
		return False


	# Start of main function

	short_filename = "ortnamn_Sverige_multipoint.geojson"
	filename = os.path.expanduser(place_name_folder + short_filename)
	if not os.path.isfile(filename):
		message ("\t*** Place name file '%s' not found - no place names will be added\n" % filename)
		url = "https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134/list/Ortnamn%20Sverige/" + short_filename
		message ("\t*** Pleae download file from '%s'\n" % url)
		return

	# Load all SSR place names in municipality

	file = open(filename)
	data = json.load(file)
	file.close()

	for feature in data['features']:
		if not "KOMMUN" in feature['properties'] or feature['properties']['KOMMUN'][1:5] == municipality_id:

			# Get best coordinate

			if feature['geometry']['type'] == "MultiPoint":
				if len(feature['geometry']['coordinates']) > 1:
					points = feature['geometry']['coordinates'][1:]
				else:
					points = feature['geometry']['coordinates']
			else:
				points = [ feature['geometry']['coordinates'] ]

			points = [ tuple(point) for point in points ]

			# Fix incorrect place type

			if feature['properties']['DETALJTYP'] == "Sjö":
				if name_match(feature['properties'], river_suffix):
					feature['properties']['DETALJTYP'] = "Vattendrag"

			elif feature['properties']['DETALJTYP'] == "Vattendrag":
				if name_match(feature['properties'], stillwater_suffix):
					feature['properties']['DETALJTYP'] = "Del av vatten"

			if feature['properties']['DETALJTYP'] in ["Vattendrag", "Del av vatten", "Sjö"]:
				if name_match(feature['properties'], ["forsen"]):
					feature['properties']['DETALJTYP'] = "Fors"

			if feature['properties']['DETALJTYP'] in ["Vattendrag", "Del av vatten", "Sjö"]:
				if name_match(feature['properties'], ["fallet"]):
					feature['properties']['DETALJTYP'] = "Vattenfall"

			# Get priority topo source

			source = ""
			for key in ["T250", "T100", "T50", "T10"]:
				if key in feature['properties']:
					source = key
					break

			entry = {
				'points':  points,
				'source': source,
				'tags': feature['properties']
			}
			place_names.append(entry)

	message ("\tLoaded %i place names from ortnamn2osm\n" % len(place_names))



# Create point with place name suggestion

def create_place_name_point(place):

	point = place['points'][0]
	tags = copy.deepcopy(place['tags'])

	if tags['DETALJTYP'] == "Del av vatten":
		if "sund"  in tags['name']:
			tags['natural'] = "strait"
		else:
			tags['natural'] = "bay"
	elif tags['DETALJTYP'] == "Fors":
		tags['natural'] = "rapids"
	elif tags['DETALJTYP'] == "Vattenfall":
		tags['waterway'] = "waterfall"

	tags['FIXME'] = "Insert " + tags.pop("DETALJTYP", None)
	create_point(point, tags, object_type = "Ortnamn")



# Function for ranking place names.
# Larger score is better.

def sort_place(place):

	topo_score = {}
	for topo in ["T250", "T100", "T50", "T10"]:
		if topo in place['tags']:
			topo_score[ topo ] = int(place['tags'][ topo ])
		else:
			topo_score[ topo ] = 0  

	score = (
#				- name_categories.index(place['tags']['DETALJTYP']),  # Only one type used
				topo_score['T250'],
				topo_score['T100'],
				topo_score['T50'],
				topo_score['T10'],
				len(place['tags']['name'].split()),  # Priority to 2+ words
				- int(place['tags']['ref:lantmateriet:ortnamn'])  # Priority to oldest numbers
			)  

	return score



# Merge place names from ortnamn2osm for given feature (polygon)

def get_place_name (feature, name_categories):

	global name_count, unused_count

	# Internal function for ranking chosen place names

	def priority_name(place1, place2):

		for topo in ["T250", "T100", "T50", "T10"]:
			if (topo in place1['tags']
					and (topo not in place2['tags']
						or int(place1['tags'][ topo ]) > int(place2['tags'][ topo ]))):
				return True

		return False


	# Start of main function.
	# Find name in stored file

	if feature['type'] == "Point":
		bbox = get_bbox(feature['coordinates'], perimeter=500)  # 500 meters perimeter to each side
	else:
		bbox = get_bbox(feature['coordinates'], perimeter=3000) 

	found_places = []

	for place in place_names[:]:
		if place['tags']['DETALJTYP'] in name_categories:
			for point in place['points']:
				if (bbox_overlap(bbox, point)
						and (feature['type'] in ["Point", "LineString"] or inside_multipolygon(point, feature['coordinates']))):

					if feature['object'] == "Hav":
						if not add_sea_names or place['tags']['name'] in avoid_sea_names:
							place_names.remove(place)  # Remove sea names
					else:
						found_places.append(place)
					break

	if not found_places:  # Also exit for "Hav"
		return

	# Create name node for bays/straits (inland)

#	if name_categories == ["Del av vatten"] and add_bay_names or feature['object'] == "Hav" and add_sea_names:
#		for place in found_places:
#			create_place_name_point(place)
#			unused_count += 1
#		return

	# For islands and wetland ensure that only topo priority place names are kept (due to large number of terrain names)

	found_places.sort(key=sort_place, reverse=True)  # Priority to T250, T100 etc.

	source = found_places[0]['source']
	if source:
		if sum(1 for place in found_places if place['source'] == source) > 5:
			source_rank = int(found_places[0]['tags'][ source ])
		else:
			source_rank = 0
	else:
		source_rank = 0

	names = set()
	for place in found_places[:]:
		if (("place" in feature['tags'] and feature['tags']['place'] in ["island", "islet"] or "Sankmark" in feature['object'])
				and source and (place['source'] != source or int(place['tags'][ source ]) < source_rank)):
			found_places.remove(place)
		elif place['tags']['name'] in names:  # Avoid duplicate names (Bottenviken, Vänern etc)
			found_places.remove(place)
			place_names.remove(place)
		else:
			names.add(place['tags']['name'])
			place_names.remove(place)

	# Establish alternative names for fixme tag

	alt_names = []
	alt_names_short = []

	for place in found_places:
		source = ""
		for key in ["T250", "T100", "T50", "T10"]:
			if key in place['tags']:
				source = " [%s-%s]" % (key, place['tags'][ key ])
				break
		alt_names.append("%s%s" % (place['tags']['name'], source))
		if place['tags']['name'] not in alt_names_short:
			alt_names_short.append(place['tags']['name'])

	# Inform about extra name if place name already is established

	if "ref:lantmateriet:ortnamn" in feature['tags'] and "name" in feature['tags']:
		found = False
		for place in found_places:
			if (place['tags']['ref:lantmateriet:ortnamn'] != feature['tags']['ref:lantmateriet:ortnamn']
					and place['tags']['name'] != feature['tags']['name']
					and ("alt_name" not in feature['tags'] or place['tags']['name'] not in feature['tags']['alt_name'].split(";"))):
				create_place_name_point(place)
				found = True

		if found:
			feature['tags']['FIXME'] = "Consider extra name: " + ", ".join(alt_names)
			if feature['tags']['name'] in alt_names_short:
				alt_names_short.remove(feature['tags']['name'])
			feature['tags']['ALT_NAME'] = ";".join(alt_names_short)

	# Add name with aproproate FIXME tag if more than one found

	else:
		new_tags = copy.deepcopy(found_places[0]['tags'])

		if len(found_places) > 1:
			if priority_name(found_places[0], found_places[1]):
				new_tags['FIXME'] = "Verify name: " + ", ".join(alt_names)
			else:
				new_tags['FIXME'] = "Choose name: " + ", ".join(alt_names)

			alt_names_short.remove(new_tags['name'])
			if alt_names_short:
				new_tags['ALT_NAME'] = ";".join(alt_names_short)

			# Create separate nodes for each alternative name

			for place in found_places:
#				if "Verify" in new_tags['FIXME'] and place['tags']['DETALJTYP'] == "Sjö":
#					place['tags']['natural'] = "bay"
				create_place_name_point(place)

		feature['tags'].update(new_tags)	
		name_count += 1



# Get place names for a category

def get_category_place_names(topo_categories, place_categories):

	global name_count, unused_count

	# Build list of features and match with place names

	category_features = []
	for feature in features:
		if (feature['object'] in topo_categories
				or "Ö" in topo_categories and "place" in feature['tags'] and feature['tags']['place'] in ["island", "islet"]):
			feature['area'] = abs(polygon_area(feature['coordinates'][0]))
			category_features.append(feature)

	category_features.sort(key=lambda feature: feature['area'], reverse=True)  # Priority to largest

	for feature in category_features:
		get_place_name(feature, place_categories)

	if topo_categories == ["Hav"]:  # Run only used for excluding sea names
		return

	# Check if remaining features have place name close outside perimeter

	remaining_features = []
	for feature in category_features:
		if "name" not in feature['tags']:
			feature['bbox'] = get_bbox(feature['coordinates'][0], perimeter=50)
			remaining_features.append(feature)

	for place in place_names[:]:
		if place['tags']['DETALJTYP'] in place_categories:  # Note: Only works if same category name across features/place names
			best_distance = 50

			for feature in remaining_features:
				for point in place['points']:
					if bbox_overlap(feature['bbox'], point):
						dist, i = shortest_distance(point, feature['coordinates'][0] )
						if dist < best_distance:
							best_feature = feature
							best_distance = dist

			if best_distance < 50:

				# Add name point for bay/strait
				if place_categories == ["Del av vatten"] and add_bay_names:
					create_place_name_point(place)
					place_names.remove(place)
					unused_count += 1

				# Else add name to feature
				else:	
					best_feature['tags'].update(place['tags'])
					del best_feature['tags']['DETALJTYP']
					remaining_features.remove(best_feature)
					place_names.remove(place)
					name_count += 1	



# Match place names with rivers

def get_river_names():

	global name_count, unused_count

	rivers = []
	for feature in features:
		if feature['object'] in ["Vattendragsyta", "Vattendrag", "Akvedukt", "Fors", "Vattentub/vattenränna", "Vattenfall", "Dammbyggnad"]:
			feature['bbox'] = get_bbox(feature['coordinates'], perimeter = 100)
			rivers.append(feature)

	# Loop each place name to determine closest fit with river.
	# Include Vattendragsyta to avoid mismatches with smaller rivers/streams.
	# No remaining Vattendrag place names after iteration.

	for place in place_names:
		if place['tags']['DETALJTYP'] in ["Vattendrag", "Vattenfall", "Fors"]:
			min_distance = 100
			for feature in rivers:
				for point in place['points']:
					if (bbox_overlap(feature['bbox'], point)
								and not (feature['object'] in ['Vattenfall', 'Fors'] and feature['object'] != place['tags']['DETALJTYP'])):
						if feature['type'] == "LineString":
							distance, index = shortest_distance(point, feature['coordinates'])
						elif feature['type'] == "Polygon":
							distance, index = shortest_distance(point, feature['coordinates'][0])  # For Vattendragsyta
						else:
							distance = point_distance(point, feature['coordinates'])  # For Vattenfall
						if distance < min_distance:
							min_distance = distance
							found_feature = feature

			if min_distance < 100 and found_feature['object'] != "Vattendragsyta":
				if "places" not in found_feature:
					found_feature['places'] = []
				found_feature['places'].append(place)  # Build list of all matched place names for feature

			elif not (topo_product == "Topo250" and place['tags']['DETALJTYP'] == "Vattendrag"):
				# Create name node if no match
				create_place_name_point(place)
				unused_count += 1

	# Assign matched river name to feature

	topo_rivers = set()  # Rivers with place name from T250/T100

	for feature in rivers:
		if "places" in feature:
			name_count += 1

			# Match with one place name
			if len(set(place['tags']['name'] for place in feature['places'])) == 1:
				for key, value in iter(feature['places'][0]['tags'].items()):
					if "name" in key or key in ["ref:lantmateriet:ortnamn", "TYPE"]:
						feature['tags'][ key ] = value

			# Match with several place names
			else:
				feature['places'].sort(key=sort_place, reverse=True)  # Priority to T250, T100 etc.
				feature['tags']['FIXME'] = "Split waterway for names: " + ", ".join(place['tags']['name'] for place in feature['places'])

				for place in feature['places']:
					create_place_name_point(place)

			# Store waterway id if high priority place name
			for place in feature['places']:
				if place['source'] in ["T250", "T100"]:
					if "vattendragsid" in feature['extras']:
						topo_rivers.add(feature['extras']['vattendragsid'])

	# Set waterway=river for this vattendragsid if matching place name had highway priority

	if not get_topo_rivers:
		for feature in rivers:
			if ("vattendragsid" in feature['extras']
					and feature['extras']['vattendragsid'] in topo_rivers
					and "waterway" in feature['tags']
					and feature['tags']['waterway'] == "stream"):
				feature['tags']['waterway'] = "river"

	# Propagate name to several segments (not used due to naming conflicts)

	'''
	river_names = {}
	for feature in rivers:
		if "vattendragsid" in feature['extras']:
			ref = feature['extras']['vattendragsid']
			if ref not in river_names:
				river_names[ ref ] = set()
			if "FIXME" in feature['tags'] and "Split" in feature['tags']['FIXME']:
				river_names[ ref ].add("FIXME")
			elif "name" in feature['tags']:
				river_names[ ref ].add(feature['tags']['name'])

	for feature in rivers:
		if "vattendragsid" in feature['extras'] and "name" not in feature['tags']:
			ref = feature['extras']['vattendragsid']
			if len(river_names[ ref ]) == 1 and list(river_names[ ref ])[0] != "FIXME":
				feature['tags']['name'] = list(river_names[ ref ])[0]
	'''


# Get place names for islands, glaciers etc.

def get_place_names():

	global name_count, unused_count

	message ("Load place names ...\n")
	lap = time.time()

	if get_hydrografi:
		load_hydrografi_lakes()

	load_place_names()

	if not place_names:
		return

	name_count = 0
	unused_count = 0

	# Pass 1: Polygon features

	get_category_place_names(["Hav"], ["Sjö", "Del av vatten"])  # Used for removing sea names

	get_category_place_names(["Ö"], ["Terräng"])  # Islands
#	get_category_place_names(["Sjö", "Anlagt vatten", "Vattendragsyta"], ["Del av vatten"])  # Bays/Straits	
	get_category_place_names(["Glaciär"], ["Glaciär"])  # Glacier
	get_category_place_names(["Sankmark, fast", "Sankmark, våt", "Sankmark"], ["Sankmark"])  # Wetland

	if not get_hydrografi:
		get_category_place_names(["Sjö", "Anlagt vatten"], ["Sjö"])  # Lakes
		# To-do: Test skären, skäret, ön, holmen, ören, grundet, grynnan, revet, hällan, örarna, klippan, klubben, bådan, grönnan, grunden, harun

	get_river_names()

	# Pass 2: Add all remaining names for sea, bay/strait and glacier (sea names may have been removed earlier)

	for place in place_names:
		if (place['tags']['DETALJTYP'] in ["Sjö", "Glaciär"] and topo_product != "Topo250"
				or place['tags']['DETALJTYP'] == "Del av vatten" and add_bay_names):
			create_place_name_point(place)
			unused_count += 1

	# Clean up tags

	for elements in [features, segments]:
		for element in elements:
			first = True
			for tag in ["T250", "T100", "T50", "T10"]:
				if tag in element['tags']:
					if not first:
						del element['tags'][ tag ]
					first = False
				if tag + "_DISTANCE" in element['tags']:
					del element['tags'][ tag + "_DISTANCE" ]
			for tag in ["KOMMUN", "DETALJTYP"]:
				if tag in element['tags']:
					del element['tags'][ tag ]

	message ("\t%i place names found\n" % name_count)
	message ("\t%i place names not matched but added as nodes\n" % unused_count)
	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))



# Get set of connections within segment between rach pair of two nodes

def get_connections (coordinates):

	connections = set()
	last_node = coordinates[0]
	for node in coordinates[1:]:
		connections.add( (last_node, node) )
		connections.add( (node, last_node) )  # Reverse
		last_node = node

	return connections



# Create new segment

def create_segment(coordinates, segment_type="Completion", used=1):

	entry = {
		'object': segment_type,
		'type': 'LineString',
		'uuid': None,
		'coordinates': coordinates.copy(),
		'members': [],
		'tags': {},
		'extras': {
			'objekttyp': segment_type
		},
		'used': used
	}
	entry['bbox'] = get_bbox(entry['coordinates'])
	segments.append(entry)
	return len(segments) - 1



# Create segments where two wetland features are overlapping

def split_overlapping_wetlands():

	# Get all wetland features

	wetland_features = []
	for feature in features:
		if "Sankmark" in feature['object']:
			feature['bbox'] = get_bbox(feature['coordinates'])
			wetland_features.append(feature)

	count = 0

	# Identify wetlands which have overlapping boundaries

	for i1, feature1 in enumerate(wetland_features):
		for i2, feature2 in enumerate(wetland_features):
			if (i2 > i1
					and feature1['object'] != feature2['object']
					and bbox_overlap(feature1['bbox'], feature2['bbox'])):

				for patch1 in feature1['coordinates']:
					for patch2 in feature2['coordinates']:
						overlap = set(patch1) & set(patch2)

						# Iterate patch1 and create new segments when overlapping patch2

						if overlap:
							connections = get_connections(patch2)

							count_new = 0
							remaining_coordinates = patch1.copy()
							last_node = remaining_coordinates.pop(0)

							while remaining_coordinates:

								# Pass segment which is not overlapping
								while remaining_coordinates and (last_node, remaining_coordinates[0]) not in connections:
									last_node = remaining_coordinates.pop(0)

								# Build segment which is overlapping
								new_coordinates = [ last_node ]
								while remaining_coordinates and (new_coordinates[-1], remaining_coordinates[0]) in connections:
									new_coordinates.append(remaining_coordinates.pop(0))

								if len(new_coordinates) > 1:
									create_segment(new_coordinates, segment_type="Sankmark gräns", used=0)
									count += 1

								last_node = new_coordinates[-1]	

	message ("\tCreated %i segments for overlapping wetland polygons\n" % count)



# Identify and split segments which are partly overlapping wetlands before full polygon splitting.
# Segment list will be modified - function must run before feature/segment mapping.

def split_wetland_segments():

	# Inner function which creates new segment based on existing segment

	def split_segment(coordinates, old_segment):

		new_segment = copy.deepcopy(old_segment)
		new_segment['coordinates'] = coordinates
		new_segment['bbox'] = get_bbox(new_segment['coordinates'])
		segments.append(new_segment)

		return new_segment


	# Main function.
	# Prepare relevant segments and line features.

	shore_segments = []
	for segment in segments:
		if ("Strandlinje" in segment['object']
				or segment['object'] == "Sankmark gräns"
				or (merge_wetland or topo_product == "Topo250") and "gräns" in segment['object']):
			segment['bbox'] = get_bbox(segment['coordinates'])
			shore_segments.append(segment)

	wetland_features = []
	for feature in features:
		if "Sankmark" in feature['object']:
			feature['bbox'] = get_bbox(feature['coordinates'])
			wetland_features.append(feature)


	# 1. Check for segments to be split

	count = len(wetland_features)
	count_split = 0

	for feature in wetland_features:

			if count % 100 == 0:
				message ("\r\t%i " % count)
			count -= 1

			for patch in feature['coordinates']:

				patch_bbox = get_bbox(patch)
				patch_set = set(patch)
				
				for segment in shore_segments:

					if bbox_overlap(patch_bbox, segment['bbox']):

						segment_set = set(segment['coordinates'])
						segment_endpoints_set = set([ segment['coordinates'][0], segment['coordinates'][-1] ])
						overlap = segment_set & patch_set

						if overlap and not segment_set <= patch_set and not overlap <= segment_endpoints_set:

							count_new = 0
							remaining_coordinates = segment['coordinates'].copy()
							new_coordinates = []

							while remaining_coordinates:

								# Build segment which is not part of patch

								while remaining_coordinates and remaining_coordinates[0] not in patch_set:
									new_coordinates.append(remaining_coordinates.pop(0))

								if new_coordinates and remaining_coordinates:
									new_coordinates.append(remaining_coordinates[0])
									if set(new_coordinates) != segment_set:
										shore_segments.append(split_segment(new_coordinates, segment))
										count_new += 1
									new_coordinates = []

								# Build segment which is part of patch

								while remaining_coordinates and remaining_coordinates[0] in patch_set:
									new_coordinates.append(remaining_coordinates.pop(0))

								if len(new_coordinates) > 1 and set(new_coordinates) != segment_set:
									shore_segments.append(split_segment(new_coordinates, segment))
									count_new += 1
								new_coordinates = [ new_coordinates[-1] ]

							if count_new > 0:
								segments.remove(segment)
								shore_segments.remove(segment)
								count_split += 1
								break

	message ("\r\tSplit %i wetland segments\n" % count_split)


	# 2. Check for missing node in wetland polygon

	count = len(shore_segments)
	count_insert = 0

	for segment in shore_segments:

		if count % 100 == 0:
			message ("\r\t%i " % count)
		count -= 1

		segment_set = set(segment['coordinates'])

		for feature in wetland_features:
			if bbox_overlap(segment['bbox'], feature['bbox']):
				for i, patch in enumerate(feature['coordinates']):

					overlap = segment_set & set(patch)
					leftover = segment_set - overlap

					if len(leftover) <= 0.5 * len(segment_set):  # Max every second node missing
						for node in leftover:
							new_patch = feature['coordinates'][ i ]  # Will be modified for each hit
							dist, j = shortest_distance(node, new_patch)
							step_distance = point_distance(new_patch[ j ], new_patch[ j + 1 ])
							if (dist < 0.2
									and point_distance(node, new_patch[ j ]) < step_distance
									and point_distance(node, new_patch[ j + 1 ]) < step_distance):

								feature['coordinates'][ i ].insert(j + 1, node)  # Insert node in patch
								create_point(node, "Missing wetland node")  # Debug
								count_insert += 1

	message ("\r\tInserted %i missing nodes in wetland polygons\n" % count_insert)


	# 3. Check for oposite: Surplus node in polygon (on straight line)

	count = len(shore_segments)
	count_remove = 0

	for segment in shore_segments:

		if count % 100 == 0:
			message ("\r\t%i " % count)
		count -= 1

		segment_set = set(segment['coordinates'])

		for feature in wetland_features:
			if bbox_overlap(segment['bbox'], feature['bbox']):
				for i, patch in enumerate(feature['coordinates']):
					patch_set = set(patch)

					if segment_set <= patch_set:

						# Determine direction
						start = patch.index(segment['coordinates'][0])
						second = patch.index(segment['coordinates'][1])
						if second > start or start == len(segment['coordinates']) - 2 and second < 2:  # Could wrap around
							end = patch.index(segment['coordinates'][-1])
						else:
							end = start
							start = patch.index(segment['coordinates'][-1])

						# Determine which intermediate nodes in patch are not found in segment
						remove_node = []
						j = start
						while j != end:
							j += 1
							if j == len(patch) - 1:  # Wrap around polygon
								j = 0

							if patch[ j ] not in segment_set and j != end:
								dist, index = shortest_distance(patch[j], segment['coordinates'])
								if dist < 0.2:
									remove_node.append(j)

						# Remove surplus node
						remove_node.sort(reverse=True)
						for j in remove_node:
							create_point(patch[ j ], "Surplus wetland node")  # Debug
							del feature['coordinates'][ i ][ j ]
							if j == 0:
								feature['coordinates'][ i ][-1] = feature['coordinates'][ i ][0]  # Ensure circle
							count_remove += 1

	message ("\r\tRemoved %i surplus nodes in wetland polygons\n" % count_remove)



# Split segments longer than 2000 nodes into smaller segments

def split_long_segments():

	count_split = 0

	for i, segment in enumerate(segments[:]):
		if segment['used'] > 0 and len(segment['coordinates']) >= 2000:
			steps = len(segment['coordinates']) // 1000
			step_length = (len(segment['coordinates']) // steps) + 1
			new_segments = []
			for j in range(steps):
				new_segment = copy.deepcopy(segment)
				new_segment['coordinates'] = segment['coordinates'][ j * step_length : (j + 1) * step_length + 1 ]
				new_segments.append(new_segment)				

			segment['coordinates'] = new_segments[0]['coordinates']
			new_members = [i]
			for new_segment in new_segments[1:]:
				segments.append(new_segment)
				new_members.append(len(segments) - 1)

			for feature in features:
				if feature['type'] == "Polygon":
					for j, member_patch in enumerate(feature['members']):
						if i in member_patch:
							for k, member in enumerate(member_patch):
								if member == i:
									feature['members'][ j ] = member_patch[ : k ] + new_members + member_patch[ k + 1 : ]  # Todo: Check order

			count_split += 1

	message ("\r\tSplit %i long segments\n" % count_split)



# Check and repair if coastline segment is not matching Hav feature

def check_coastline():

	# Inner function for matching coastline segment with Hav

	def check_match(segment):

		nonlocal sea_features

		segment_bbox = get_bbox([ segment['coordinates'][0], segment['coordinates'][-1] ])
		segment_set = set(segment['coordinates'])
		for feature in sea_features:
			if bbox_overlap(segment_bbox, feature['bbox']):
				for patch in feature['coordinates']:
					if segment['coordinates'][0] in patch or segment['coordinates'][-1] in patch:

						missing = segment_set - set(patch)
						if len(missing) == 0:
							return False
						elif len(missing) == 1:
							missing_node = list(missing)[0]
							for i, node in enumerate(patch):
								if node not in segment_set:
									if point_distance(node, missing_node) < 0.01:
										patch[ i ] = missing_node
										return True
		return False


	# Start of main function

	sea_features = []
	for feature in features:
		if feature['object'] == "Hav":
			feature['bbox'] = get_bbox(feature['coordinates'][0])
			sea_features.append(feature)

	count_repair = 0
	for segment in segments:
		if segment['object'] in ["Strandlinje, hav", "Stängning mot hav"]:
			if check_match(segment):
				count_repair += 1

	message ("\tRepaired %i coastline segments\n" % count_repair)



# Create missing segments to get complete polygons

def create_missing_segments (patch, members):

	# First create list of existing conncetions between coordinates i and i+1 of patch

	connections = set()
	for member in members:
		connections.update(get_connections(segments[ member ]['coordinates']))

	# Then create new segments for the parts of patch which have no segments

	count_new = 0
	remaining_coordinates = patch.copy()
	last_node = remaining_coordinates.pop(0)

	while remaining_coordinates:

		# Pass segment which is already part of a member

		while remaining_coordinates and (last_node, remaining_coordinates[0]) in connections:
			last_node = remaining_coordinates.pop(0)

		# Build segment which is missing

		new_coordinates = [ last_node ]

		while remaining_coordinates and (new_coordinates[-1], remaining_coordinates[0]) not in connections:
			new_coordinates.append(remaining_coordinates.pop(0))

		if len(new_coordinates) > 1:
			member_id = create_segment(new_coordinates, used=1)
			members.append( member_id )
			count_new += 1
			connections.update(get_connections(new_coordinates))

		last_node = new_coordinates[-1]



# Function for getting priority of feature objects.

def feature_order(feature):
	if feature['object'] in object_sorting_order:
		return object_sorting_order.index(feature['object'])
	else:
		return 100



# Create relation/member data structure:
# - Fix wetlands segments
# - Split polygons into segments
# - Order direction of ways for coastline, lakes, rivers and islands
# - Order members of multipolygons
# - Crate missing segments along municipality border
# - Combine sequences of segments

def create_relations_structure():

	# Function for sorting member segments of polygon relation
	# Index 1 used to avoid equal 0/-1 positions

	def segment_position(segment_index, patch):
		coordinates = segments[ segment_index ]['coordinates']
		if len(coordinates) == 2:
			if coordinates == patch[-2:] or coordinates == patch[-1:-3:-1]:  # Last two nodes
				return len(patch)
			else:
				return max(patch.index(coordinates[0]), patch.index(coordinates[1]))
		else:
			return patch.index(coordinates[1])


	if data_category in ["topo", "mark"]:
		message ("Repair source geometry ...\n")
		check_coastline()
		if topo_product not in ["Topo50", "Topo100"]:
			if topo_product == "Topo10":
				split_overlapping_wetlands()
			split_wetland_segments()

	message ("Create topo relations ...\n")

	# Create bbox for segments and line features

	for segment in segments:
		segment['bbox'] = get_bbox(segment['coordinates'])

	# Loop all polygons and patches

	lap = time.time()
	split_count = 0
	count = sum([feature['type'] == "Polygon" for feature in features])

	ordered_features = copy.copy(features)  # Shallow copy of list
	ordered_features.sort(key=feature_order)  # Sort first coastline, lakes, rivers etc.

	for feature in ordered_features:

		if feature['type'] != "Polygon":
			continue

		if count % 100 == 0:
			message ("\r\t%i " % count)
		count -= 1
		matching_polygon = []

		for patch in feature['coordinates']:
			matching_segments = []
			matched_nodes = 0
			patch_set = set(patch)
			patch_connections = set()

			# Try matching with segments within the polygon's bbox

			patch_bbox = get_bbox(patch)

			for i, segment in enumerate(segments):

				if bbox_overlap(patch_bbox, segment['bbox']) and set(segment['coordinates']) <= patch_set:

					segment_connections = get_connections(segment['coordinates'])
					if segment_connections & patch_connections:
						continue

					# Note: If patch is a closed way, segment may wrap start/end of patch

					if len(segment['coordinates']) >= 2:
						node1 = patch.index(segment['coordinates'][0])
						node2 = patch.index(segment['coordinates'][-1])
						if (not(abs(node1 - node2) == len(segment['coordinates']) - 1
									or patch[0] == patch[-1] and abs(node1 - node2) == len(patch) - len(segment['coordinates']))):
							continue

					# Only exact match permitted for wetland if Topo50, 100, 250
					if "Sankmark" in feature['object'] and topo_product in ["Topo50", "Topo100"] and set(segment['coordinates']) != patch_set:
						continue

					# Avoid special case of Stängning segment used in sea
					if feature['object'] == "Hav" and segment['object'] == "Stängning":
						continue

					matching_segments.append( i )
					matched_nodes += len(segment['coordinates']) - 1
					patch_connections.update(segment_connections)

					# Correct direction of segments. Note sorting order of features in outer loop.

					if (feature['object'] in ['Hav', 'Sjö', 'Anlagt vatten', 'Vattendragsyta']
							and "Strandlinje" in segment['object'] or "Stängning" in segment['object']):

						# Check if feature polygon and segment line have same direction
						node1 = patch.index(segment['coordinates'][0])
						node2 = patch.index(segment['coordinates'][1])
						same_direction = node1 + 1 == node2 or patch[0] == patch[-1] and node1 == len(patch) - 2 and node2 == 0

						if not same_direction and segment['used'] == 0:
							segment['coordinates'].reverse()
							segment['extras']['reversert'] = "yes"

						segment['used'] += 1

					elif feature['object'] != "Hav":
						segment['used'] += 1

					if len(patch_connections) == 2 * (len(patch) - 1):   # matched_nodes == len(patch) - 1:
						break

			if matching_segments:
				# Use leftover nodes to create missing border segments
				if len(patch_connections) < 2 * (len(patch) - 1) and feature['object'] != "Hav":   #  matched_nodes < len(patch) - 1 
					create_missing_segments(patch, matching_segments)

				# Sort relation members for better presentation
				matching_segments.sort(key=lambda segment_index: segment_position(segment_index, patch))
				matching_polygon.append(matching_segments)
				split_count += len(matching_segments) - 1
			else:
#				message ("\t*** NO MATCH: %s\n" % (feature['uuid']))
#				feature['extras']['segmentering'] = "no"
				member = create_segment(patch, used=1)
				matching_polygon.append([ member ])

		if matching_polygon:
			feature['members'] = matching_polygon
		else:
			# Backup output
			feature['type'] = "LineString"
			feature['coordinates'] = feature['coordinates'][0]
			feature['tags']['FIXME'] = "Repair polygon"

	message ("\r\tSplit polygons into %i segments\n" % split_count)

	# Simplify and combine geometry

	if simplify:
		if merge_grid:
			combine_features()
		combine_segments()
		split_long_segments()

	# Note: After this point, feature['coordinates'] may not exactly match member segments.

	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))



# Reorder outer members of feature.
# Used after combining two touching features.

def fix_member_order(feature):

	# Identify each ring and build list of rings (patches)

	remaining_members = copy.deepcopy(feature['members'][0])
	polygon_patches = []
	found = True

	while remaining_members and found:
		coordinates = copy.copy(segments[ remaining_members[0] ]['coordinates'])
		patch = [ remaining_members[0] ]
		start_member = patch[0]
		remaining_members.pop(0)
		patch_direction = 1
		found = True

		# Keep adding members as long as they match end-to-end

		while found:
			found = False
			for member in remaining_members:
				member_coordinates = segments[ member ]['coordinates']
				if coordinates[-1] == member_coordinates[0]:
					coordinates.extend(member_coordinates[1:])
					patch.append(member)
					direction = 1
				elif coordinates[-1] == member_coordinates[-1]:
					coordinates.extend(list(reversed(member_coordinates))[1:])
					patch.append(member)
					direction = -1
				else:
					continue

				patch_direction += direction
				remaining_members.remove(member)
				found = True
				break

		if coordinates[0] == coordinates[-1]:
			polygon_patch = {
				'members': patch,
				'coordinates': coordinates
			}
			polygon_patches.append(polygon_patch)
			found = True

	if not remaining_members and polygon_patches:
		for patch in polygon_patches:
			patch['area'] = polygon_area(patch['coordinates'])

		polygon_patches.sort(key=lambda patch: abs(patch['area']), reverse=True)  # Largest/outer polygon first
		feature['coordinates'] = [ patch['coordinates'] for patch in polygon_patches ] + feature['coordinates'][1:]
		feature['members'] = [ patch['members'] for patch in polygon_patches ] + feature['members'][1:]
	else:
		message ("\t*** UNORDERED MEMBERS: %s\n" % feature['uuid'])



# Combine features across Gridline

def combine_features():

	# Get list of parents (features) for each segment.

	for segment in segments:
		segment['parents'] = []

	for i, feature in enumerate(features):
		if feature['type'] == "Polygon":
			for member in feature['members'][0]:
				segments[ member ]['parents'].append(i)

	# Loop segment and combine asociated features if Gridline is found

	remove_features = []  # Will contain all features to be removed after combination

	for i, segment in enumerate(segments):
		if (segment['object'] == "Gridline"
				and segment['used'] > 0
				and len(segment['parents']) == 2
				and features[ segment['parents'][0] ]['object'] == features[ segment['parents'][1] ]['object']
				and segment['parents'][0] != segment['parents'][1]
				and	not (features[ segment['parents'][0] ]['object'] in ["Barr- och blandskog", "Skog"]  # 'Lövskog'
						and (len(features[ segment['parents'][0] ]['members'][0]) > max_combine_members
								and len(features[ segment['parents'][1] ]['members'][0]) > max_combine_members
							or on_grid_cross(segment['coordinates'])))):  

			feature1 = features[ segment['parents'][0] ]  # To keep
			feature2 = features[ segment['parents'][1] ]  # To include in feature1
			feature1_index = segment['parents'][0]
			feature2_index = segment['parents'][1]
			if len(feature2['members'][0]) > max_combine_members or len(feature2['members'][0]) > len(feature1['members'][0]):
				feature1, feature2 = feature2, feature1
				feature1_index, feature2_index = feature2_index, feature1_index

			# Exclude features with KantUtsnitt
#			if (feature2['object'] in ['Lövskog', 'Barr- och blandskog']
#					and	any([segments[ member ]['object'] == "KantUtsnitt" for member in feature2['members'][0]])):
#				continue

			# Inner roles not supported
			if i not in feature1['members'][0] or i not in feature2['members'][0]:
				continue

			# Update list of combined members

			removed_members = []

			for member1 in feature1['members'][0][:]:
				if member1 in feature2['members'][0]:
					feature1['members'][0].remove(member1)  # Remove all common members
					removed_members.append(member1)
					segments[ member1 ]['used'] -= 2

			for member2 in feature2['members'][0]:
				if member2 not in removed_members:
					feature1['members'][0].append(member2)  # Merge into relation1
					segments[ member2 ]['parents'].append(feature1_index)
					segments[ member2 ]['parents'].remove(feature2_index)

			for patch in feature2['members'][1:]:
				feature1['members'].append(patch)

			for patch in feature2['coordinates'][1:]:
				feature1['coordinates'].append(patch)

			fix_member_order(feature1)

			remove_features.append(feature2_index)

	# Remove features, starting at end of feature list

	remove_features.sort(reverse=True)
	for i in remove_features:
		del features[ i ]

	message ("\tCombined %i features\n" % len(remove_features))



# Combine sequences of segments/ways which have the same type, parents and tags

def combine_segments():

	# Internal function to update segments and features with the identified combinations of segments

	def update_segments_and_features(combinations):

		# Update segments with combinations

		remove = set()  # Will contain all segments to be combined into another segment
		for combine in combinations:

			# Get correct order for combined string of coordinates

			if segments[ combine[0] ]['coordinates'][-1] in segments[ combine[1] ]['coordinates']:
				coordinates = [ segments[ combine[0] ]['coordinates'][0] ]
			else:
				coordinates = [ segments[ combine[0] ]['coordinates'][-1] ]

			for segment_id in combine:
				segment = segments[ segment_id ]
				if segment['coordinates'][0] == coordinates[-1]:
					coordinates.extend(segment['coordinates'][1:])
				elif segment['coordinates'][-1] == coordinates[-1]:
					coordinates.extend(list(reversed(segment['coordinates']))[1:])
				elif segment['coordinates'][1] == coordinates[-1]:
					coordinates.extend(segment['coordinates'][2:])
				elif segment['coordinates'][-2] == coordinates[-1]:
					coordinates.extend(list(reversed(segment['coordinates']))[2:])
				else:
#					message ("*** SEGMENTS DISCONNECTED: %s\n" % str(segment['coordinates'][1]))
					coordinates.extend(segment['coordinates'])

			# Keep the first segment in the sequence
			segments[ combine[0] ]['coordinates'] = coordinates
			segments[ combine[0] ]['extras']['combine'] = str(len(combine))

			for segment_id in combine[1:]:
				segments[ segment_id ]['used'] = 0  # Mark as not in use/not for output
				remove.add(segment_id)

		# Update features with combinations

		for feature in features:
			if feature['type'] == "Polygon":
				new_members = []
				for patch in feature['members']:
					new_patch = []
					for member in patch:
						if member not in remove:
							new_patch.append(member)
					new_members.append(new_patch)
				if new_members != feature['members']:
					feature['members'] = new_members


	# Start of main function.
	# Part 1: Get list of parents (features) for each segment.

	for segment in segments:
		segment['parents'] = set()

	for i, feature in enumerate(features):
		if feature['type'] == "Polygon":
			for j, patch in enumerate(feature['members']):
				for member in patch:
					segments[ member ]['parents'].add(( i, j ))  # tuple

	# Part 2: Combine segments within each feature polygon (not across features/polygons)

	ordered_features = copy.copy(features)  # Shallow copy of list
	ordered_features.sort(key=feature_order)  # Sort first coastline, lakes, rivers etc.

	combinations = []  # Will contain all sequences to combine
	for feature in ordered_features:
		if feature['type'] == "Polygon":
			for patch in feature['members']:
				first = True
				remaining = patch[:]

				while remaining:
					combine = [ remaining.pop(0) ]

					# Build sequence of segments until different
					while (remaining
							and segments[ combine[0] ]['parents'] == segments[ remaining[0] ]['parents']
							and segments[ combine[0] ]['object'] == segments[ remaining[0] ]['object']
							and segments[ combine[0] ]['tags'] == segments[ remaining[0] ]['tags']
							and set([ segments[ combine[-1] ]['coordinates'][0], segments[ combine[-1] ]['coordinates'][-1] ])
									& set([ segments[ remaining[0] ]['coordinates'][0], segments[ remaining[0] ]['coordinates'][-1] ])):
						combine.append(remaining.pop(0))

					if first and len(combine) < len(patch):
						remaining.extend(combine)  # Wrap around end to check longer sequence
					elif len(combine) > 1 and not any([set(combine) == set(c) for c in combinations]):
						combinations.append(combine)
					first = False

	update_segments_and_features(combinations)
	count_segments = sum([len(combine) for combine in combinations])
	count_combinations = len(combinations)


	# Part 3: Combine remaining coastline combinations across features/polygons (ways split due to Hav grids)

	# Get relevant coastline segments, i.e. which are next to Gridline segments

	coastlines = []
	for j, feature in enumerate(features):
		if feature['object'] == "Hav" and len(feature['members']) > 0:
			patch = feature['members'][0]
			n = len(patch)
			for i, member in enumerate(patch):  # Only outer patch
				segment = segments[ member ]
				if (segment['object'] in ["Strandlinje, hav", "Stängning mot hav"]
						and (segments[ patch[ (i-1) % n ] ]['object'] == "Gridline"
							or segments[ patch[ (i+1) % n ] ]['object'] == "Gridline")):
					coastlines.append(member)
					segment['parents'].remove((j,0))  # Outer patch 0

	# Merge coastline segments until exhausted

	combinations = []
	while coastlines: 
		segment1 = segments[ coastlines[0] ]
		combine = [ coastlines.pop(0) ]
		first_node = segment1['coordinates'][0]
		last_node = segment1['coordinates'][-1]

		# Build sequence of coastline segments until closed way or differnt

		found = True
		while found and first_node != last_node:
			found = False
			for segment_id in coastlines[:]:
				segment2 = segments[ segment_id ]
				if (segment2['coordinates'][0] == last_node
						and segment2['parents'] == segment1['parents']
						and segment2['tags'] == segment1['tags']):
					last_node = segment2['coordinates'][-1]
					combine.append(segment_id)
					coastlines.remove(segment_id)
					found = True
					break

		if len(combine) > 1:
			combinations.append(combine)

	update_segments_and_features(combinations)
	count_segments += sum([len(combine) for combine in combinations])
	count_combinations += len(combinations)

	message ("\tCombined %i segments into %i longer segments\n" % (count_segments, count_combinations))



# Identify islands and add island tagging.

def identify_islands():

	message ("Identify islands...\n")

	island_count = 0

	# Part 1: Identify islands described by inner parts of lakes and sea
	# First build list of other candidate relations

	candidates = []
	for feature in features:
		if (len(feature['members']) == 1
#				and len(feature['members'][0]) > 1
				and feature['object'] not in ['Sjö', 'Anlagt vatten', 'Vattendragsyta', 'Hav']):
			found = True
			for member in feature['members'][0]:
				if segments[ member ]['object'] not in ['Strandlinje, sjö', 'Strandlinje, anlagt vatten', 'Strandlinje, vattendragsyta',
														'Strandlinje, hav', 'Stängning', 'Stängning mot hav']:
					found = False
					break
			if found:
				candidates.append(feature)

	# Loop all inner objects of multipolygon lakes and sea

	for feature in features:
		if feature['object'] in ['Sjö', 'Anlagt vatten', 'Vattendragsyta', 'Hav']:
			for i in range(1, len(feature['members'])):

				# Determine island type based on area

				area = polygon_area(feature['coordinates'][i])

				if abs(area) > island_size:
					island_type = "island"
				else:
					island_type = "islet"

				# Tag closed way if possible

				found = False
				'''
				# Omit this section, create new island feature instead
				if len(feature['members'][i]) == 1:
					segment = segments[ feature['members'][i][0] ]
					if segment['tags']:  #"natural" in segment['tags'] and segment['tags']['natural'] == "coastline":  # and "intermittent" not in segment['tags']:
						segment['tags']['place'] = island_type
						segment['extras']['area'] = str(int(abs(area)))
						island_count += 1						
						found = True
				'''

				# Else search for already existing relation

				if not found:
					for feature2 in candidates:
						if set(feature['members'][i]) == set(feature2['members'][0]):
							# Avoid water type islands
							if not ("natural" in feature2['tags'] and feature2['tags']['natural'] == "wetland" and len(feature2['members']) == 1):
								feature2['tags']['place'] = island_type
								feature2['extras']['area'] = str(int(abs(area)))
								island_count += 1
							found = True
							break

				# Else create new polygon

				if not found:
					entry = {
						'object': "Ö",
						'type': 'Polygon',
						'coordinates': [ copy.deepcopy(feature['coordinates'][i]) ],
						'members': [ copy.deepcopy(feature['members'][i]) ],
						'tags': { 'place': island_type },
						'extras': { 'area': str(int(abs(area))) }
					}

					features.append(entry)
					island_count += 1

	if debug:
		message ("\t%i islands\n" % island_count)

	# Part 2: Identify remaining islands
	# First check islands in sea, then check islands which are combinations of rivers, lekes and/or sea (in river deltas)

	used_segments = []

	for part in ["coastline", "coastline/river/water"]:
		coastlines = []

		# First build unordered list of segment coastline

		if part == "coastline":
			# Pass 2a: First check natural=coastline only (seawater)
			# Example: Senja (which also has rivers)

			for feature in features:
				if feature['object'] == "Hav" and len(feature['members']) > 0:
					for member in feature['members'][0]:  # Only outer patch
						segment = segments[ member ]
						if segment['object'] in ['Strandlinje, hav', 'Stängning mot hav']:
							coastlines.append(segment)

		else:
			# Pass 2b: Then check combinations of lakes, rivers and coastline
			# Examples: Kråkerøy (Fredrikstad), Holmen (Drammen), Øyna (Iveland)

			for feature in features:
				if (feature['object'] in ['Sjö', 'Anlagt vatten', 'Vattendragsyta', 'Hav']
						and len(feature['members']) > 0
						and any(segments[ member ]['object'] in ['Strandlinje, sjö', 'Strandlinje, anlagt vatten', 'Strandlinje, vattendragsyta',
																'Strandlinje, hav', 'Stängning', 'Stängning mot hav', 'Gridline']
								for member in feature['members'][0])):  # Only features which are connected

					for member in feature['members'][0]:  # Only outer patch
						segment = segments[ member ]
						if (segment['object'] in ['Strandlinje, sjö', 'Strandlinje, anlagt vatten', 'Strandlinje, vattendragsyta', 'Strandlinje, hav']
								and member not in used_segments):  # Exclude any islands already identified
							coastlines.append(segment)

		# Merge coastline segments until exhausted

		while coastlines: 
			segment = coastlines[0]
			island = [ coastlines[0] ]
			coastlines.pop(0)
			first_node = segment['coordinates'][0]
			last_node = segment['coordinates'][-1]

			# Build coastline/island forward

			found = True
			while found and first_node != last_node:
				found = False
				for segment in coastlines[:]:
					if segment['coordinates'][0] == last_node:
						last_node = segment['coordinates'][-1]
						island.append(segment)
						coastlines.remove(segment)
						found = True
						break

			# Add island to features list if closed chain of ways

			if first_node == last_node:

				members = []
				coordinates = [ first_node ]
				for segment in island:
					members.append(segments.index(segment))
					coordinates += segment['coordinates'][1:]

				area = polygon_area(coordinates)
				if area < 0:
					continue  # Avoid lakes

				used_segments.extend(members)  # Exclude in next pass

				if abs(area) > island_size:
					island_type = "island"
				else:
					island_type = "islet"

				# Reuse existing relation if possible

				found = False
				for feature in candidates:
					if set(members) == set(feature['members'][0]):
						feature['tags']['place'] = island_type
						feature['extras']['area'] = str(int(abs(area)))
						island_count += 1
						found = True
						break

				# Else create new relation for island

				if not found:
					entry = {
						'object': "Ö",
						'type': 'Polygon',
						'coordinates': [ coordinates ],
						'members': [ members ],
						'tags': copy.deepcopy(island[0]['tags']),
						'extras': copy.deepcopy(island[0]['extras'])
					}

					entry['tags']['place'] = island_type
					entry['tags'].pop("natural", None)  # Remove natural=coastline (already on segments)
					entry['extras']['area'] = str(int(abs(area)))

					features.append(entry)
					island_count += 1

	message ("\t%i islands\n" % island_count)



# Identify common intersection nodes between lines (e.g. streams)

def identify_intersections():

	global delete_count

	message ("Identify line intersections...\n")

	lap = time.time()
	node_count = len(nodes)
	delete_count = 0
	river_count = 0

	# Make sure all Hav are removed

	for feature in features[:]:
		if feature['object'] == "Hav":
			features.remove(feature)

	# Create set of common nodes for segment intersections

	for segment in segments:
		if segment['used'] > 0:
			nodes.add(segment['coordinates'][0])
			nodes.add(segment['coordinates'][-1])

	for feature in features:
		if feature['type'] == "LineString":
			nodes.add(feature['coordinates'][0])
			nodes.add(feature['coordinates'][-1])

	if merge_node:

		# Create bbox for segments and line features + create temporary list of LineString features

		for segment in segments:
			if segment['used'] > 0:
				segment['bbox'] = get_bbox(segment['coordinates'])
		
		# Loop streams to identify intersections with segments

		count = sum([feature['type'] == "LineString" and feature['object'] == "Vattendrag" for feature in features])

		for feature in features:
			if feature['type'] == "LineString" and feature['object'] == "Vattendrag":
				feature['bbox'] = get_bbox(feature['coordinates'])
				if count % 100 == 0:
					message ("\r\t%i " % count)
				count -= 1

				for segment in segments:
					if (segment['used'] > 0 or debug) and bbox_overlap(feature['bbox'], segment['bbox']):

						intersections = set(feature['coordinates']).intersection(set(segment['coordinates']))

						# Insert new node in segment if on line but no hit on existing node

						if len(intersections) == 0:
							if feature['object'] == "Vattendrag" and ("Strandlinje" in segment['object'] or "Stängning" in segment['object']):
								for end in [0, -1]:
									river_point = feature['coordinates'][ end ]
									dist, i = shortest_distance(river_point, segment['coordinates'])
									if dist < 0.1:
										dist, lake_point = line_distance(segment['coordinates'][i], segment['coordinates'][i+1],
																	river_point, get_point = True)
										if point_distance(lake_point, segment['coordinates'][ i ]) < 0.1:
											feature['coordinates'][ end ] = segment['coordinates'][ i ]
										elif point_distance(lake_point, segment['coordinates'][ i+1 ]) < 0.1:
											feature['coordinates'][ end ] = segment['coordinates'][ i+1 ]
										else:
											lake_point = ( round(lake_point[0], precision), round(lake_point[1], precision) )
											feature['coordinates'][ end ] = lake_point
											segment['coordinates'].insert(i+1, lake_point)
										nodes.discard(river_point)
										nodes.add(feature['coordinates'][ end ])
										river_count += 1
										break
							continue

						# Relocate node to avoid connection

						for node in intersections:
							index1 = feature['coordinates'].index(node)
							index2 = segment['coordinates'].index(node)

							# First check if stream node may be removed or slightly relocated

							if "Strandlinje" in segment['object'] or "Stängning" in segment['object']:
								nodes.add( node )

							elif index1 not in [0, len(feature['coordinates']) - 1] and node not in nodes:
								if (feature['coordinates'][ index1 - 1] not in intersections
										and feature['coordinates'][ index1 + 1] not in intersections):
									feature['coordinates'].pop(index1)
									delete_count += 1
								else:
									lon, lat = node
									offset = 10 ** (- precision + 1)  # Last lat/lon decimal digit
									feature['coordinates'][index1] = ( lon + 4 * offset, lat + 2 * offset )
									# Note: New node used in next test here

								# Then check if segment node may also be removed

								if index2 not in [0, len(segment['coordinates']) - 1]:
									if (segment['coordinates'][ index2 - 1] not in intersections
											and segment['coordinates'][ index2 + 1] not in intersections
											and line_distance(segment['coordinates'][ index2 - 1], segment['coordinates'][ index2 + 1],
																segment['coordinates'][ index2 ]) < simplify_factor):
										segment['coordinates'].pop(index2)		

	message ("\r\tConnected %i streams to lakes\n" % river_count)
	message ("\t%i common nodes, %i nodes removed from streams and auxiliary lines\n" % (len(nodes) - node_count, delete_count))
	message ("\tRun time %s\n" % (timeformat(time.time() - lap)))



# Reduce number of nodes in geometry lines

def simplify_geometry():

	# Partition line into sublines at intersections before simplifying each partition

	def partition_and_simplify(line):

		remaining = copy.copy(line)
		new_line = [ remaining.pop(0) ]

		while remaining:
			subline = [ new_line[-1] ]

			while remaining and not remaining[0] in nodes:  # Continue until tagged or intersecting
				subline.append(remaining.pop(0))

			if remaining:
				subline.append(remaining.pop(0))

			new_line += simplify_line(subline, simplify_factor)[1:]

		return new_line


	# Simplify all lines which will be included in output

	message ("\tSimplify geometry by %.1f factor ... " % simplify_factor)

	new_count = 0
	old_count = 0

	for segment in segments:
		if (segment['used'] > 0
				and not (segment['coordinates'][0] == segment['coordinates'][-1]
						and len(segment['coordinates']) <= 4)):
			old_count += len(segment['coordinates'])
			segment['coordinates'] = partition_and_simplify(segment['coordinates'])
			new_count += len(segment['coordinates'])

	for feature in features:
		if feature['type'] == "LineString":
			old_count += len(feature['coordinates'])
			feature['coordinates'] = partition_and_simplify(feature['coordinates'])
			new_count += len(feature['coordinates'])		

	if old_count > 0:
		removed = 100.0 * (old_count - new_count) / old_count
	else:
		removed = 0

	# Check polygons which may have collapsed

	feature_count = 0
	for feature in features[:]:
		if feature['type'] == "Polygon":
			for i, patch in enumerate(feature['members'][:]):
				if len(patch) == 2 and len(set(segments[ patch[0] ]['coordinates'] + segments[ patch[1] ]['coordinates'])) == 2:
					for j in [0,1]:
						segments[ patch[j] ]['used'] -= 1
						if ("FIXME" in segments[ patch[j] ]['tags']
								and segments[ patch[j] ]['tags']['FIXME'] == "Merge"):
							del segments[ patch[j] ]['tags']['FIXME']
					del feature['members'][i]
					del feature['coordinates'][i]
					feature_count += 1
			if not feature['members']:
				features.remove(feature)

	message ("%i nodes removed (%i%%)" % (old_count - new_count, removed))
	if feature_count:
		message (", %i features removed" % feature_count)
	message ("\n")



# Save geojson file for reviewing raw input data from GML file

def save_geojson(filename):

	message ("Save to '%s' file...\n" % filename)

	json_features = { 
		'type': 'FeatureCollection',
		'features': []
	}

	for i, segment in enumerate(segments):
		segment['tags']['segment'] = str(i)


	for feature_list in [features, segments]:
		for feature in feature_list:
			entry = {
				'type': 'Feature',
				'geometry': {
					'type': feature['type'],
					'coordinates': feature['coordinates']
				},
				'properties': dict(list(feature['extras'].items())
									+ list(feature['tags'].items())
									+ list({ 'geometri': feature['type'] }.items()))
			}

			json_features['features'].append(entry)

	file = open(filename, "w")
	json.dump(json_features, file, indent=1, ensure_ascii=False)
	file.close()

	message ("\t%i features saved\n" % len(features))



# Indent XML output

def indent_tree(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_tree(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i



# Save osm file

def save_osm(filename):

	message ("Save to '%s' file...\n" % filename)

	for i, segment in enumerate(segments):
		if segment['used'] > 0:
			nodes.add(segment['coordinates'][0])
			nodes.add(segment['coordinates'][-1])
			if debug:
				segment['extras']['SEGMENT'] = str(i)

	for feature in features:
		if feature['type'] == "LineString":
			nodes.add(feature['coordinates'][0])
			nodes.add(feature['coordinates'][-1])

	if simplify:
		simplify_geometry()

	osm_node_ids = {}  # Will contain osm_id of each common node
	relation_count = 0
	way_count = 0
	node_count = 0

	osm_root = ET.Element("osm", version="0.6", generator="topo2osm v"+version, upload="false")
	osm_id = -1000

	# Common nodes

	for node in nodes:
		osm_id -= 1
		osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[1]), lon=str(node[0]))
#		if debug:
#			osm_node.append(ET.Element("tag", k="OSMID", v=str(osm_id)))

		osm_root.append(osm_node)
		osm_node_ids[ node ] = osm_id
		node_count += 1

	# Ways used by relations

	for segment in segments:
		if segment['used'] > 0 or debug:
			osm_id -= 1
			osm_feature = ET.Element("way", id=str(osm_id), action="modify")
			osm_root.append(osm_feature)
			segment['osm_id'] = osm_id
			segment['etree'] = osm_feature
			way_count += 1

			for node in segment['coordinates']:
				if node in nodes:
					osm_nd = ET.Element("nd", ref=str(osm_node_ids[ node ]))
				else:
					osm_id -= 1
					osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[1]), lon=str(node[0]))
					osm_root.append(osm_node)
					osm_nd = ET.Element("nd", ref=str(osm_id))
					node_count += 1
				osm_feature.append(osm_nd)

			for key, value in iter(segment['tags'].items()):
				osm_tag = ET.Element("tag", k=key, v=value)
				osm_feature.append(osm_tag)

			if debug:
				osm_feature.append(ET.Element("tag", k="OSMID", v=osm_feature.attrib['id']))
				for key, value in iter(segment['extras'].items()):
					osm_tag = ET.Element("tag", k=key.upper(), v=value)
					osm_feature.append(osm_tag)

	# The main objects

	for feature in features:

		if feature['object'] == "Hav":
			continue

		if feature['type'] == "Point":
			if feature['coordinates'] in nodes:
				osm_feature = osm_root.find("node[@id='%i']" % osm_node_ids[ feature['coordinates'] ] )  # Point already created
			else:
				osm_id -= 1
				osm_feature = ET.Element("node", id=str(osm_id), action="modify", lat=str(feature['coordinates'][1]), lon=str(feature['coordinates'][0]))
				osm_root.append(osm_feature)
				node_count += 1

		elif feature['type'] in "LineString":
			osm_id -= 1
			osm_feature = ET.Element("way", id=str(osm_id), action="modify")
			osm_root.append(osm_feature)
			way_count += 1

			for node in feature['coordinates']:
				if node in nodes:
					osm_nd = ET.Element("nd", ref=str(osm_node_ids [ node ]))
				else:
					osm_id -= 1
					osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[1]), lon=str(node[0]))
					osm_root.append(osm_node)
					osm_nd = ET.Element("nd", ref=str(osm_id))
					node_count += 1
				osm_feature.append(osm_nd)

		elif feature['type'] == "Polygon":

			# Output way if possible to avoid relation
			if (len(feature['members']) == 1
					and len(feature['members'][0]) == 1
					and not ("natural" in feature['tags'] and "natural" in segments[ feature['members'][0][0] ]['tags'])):

				segments[ feature['members'][0][0] ]['tags'].update(feature['tags'])  # Avoid confict if another overlapping feature
				osm_feature = segments[ feature['members'][0][0] ]['etree']

				# Add area=yes for piste:type=downhill when closed ways (not needed for relations)
				if "piste:type" in feature['tags']:
					osm_tag = ET.Element("tag", k="area", v="yes")
					osm_feature.append(osm_tag)

			else:
				osm_id -= 1
				osm_feature = ET.Element("relation", id=str(osm_id), action="modify")
				osm_root.append(osm_feature)
				relation_count += 1
				role = "outer"

				for patch in feature['members']:
					for member in patch:
						if "osm_id" in segments[ member ]:
							osm_member = ET.Element("member", type="way", ref=str(segments[ member ]['osm_id']), role=role)
							osm_feature.append(osm_member)
						else:
							message ("\t*** NO OSM_ID: %s\n" % segments[ member ]['uuid'])
					role = "inner"

				osm_tag = ET.Element("tag", k="type", v="multipolygon")
				osm_feature.append(osm_tag)

		else:
			message ("\t*** UNKNOWN GEOMETRY: %s\n" % feature['type'])

		for key, value in iter(feature['tags'].items()):
			osm_tag = ET.Element("tag", k=key, v=value)
			osm_feature.append(osm_tag)

		if debug:
			osm_feature.append(ET.Element("tag", k="OSMID", v=osm_feature.attrib['id']))
			for key, value in iter(feature['extras'].items()):
				osm_tag = ET.Element("tag", k=key.upper(), v=value)
				osm_feature.append(osm_tag)


	osm_root.set("upload", "false")
	indent_tree(osm_root)
	osm_tree = ET.ElementTree(osm_root)
	osm_tree.write(filename, encoding='utf-8', method='xml', xml_declaration=True)

	message ("\t%i relations, %i ways, %i nodes saved\n" % (relation_count, way_count, node_count))


# Main program

if __name__ == '__main__':

	start_time = time.time()
	message ("\n-- topo2osm v%s --\n" % version)

	features = []        	# All geometry and tags
	segments = []        	# Line segments which are shared by one or more polygons
	nodes = set()        	# Common nodes at intersections, including start/end nodes of segments [lon,lat]
	place_names = []		# Place names ("ortnamn") from Lantmäteriet
	building_tags = {}   	# Conversion table from building type to osm tag


	# Parse parameters

	if len(sys.argv) < 2:
		message ("Please provide municipality, and optional data category parameter.\n")
		message ("Data categories: %s\n" % ", ".join(data_categories))
		message ("Options: -seanames, -baynames, -wetland, -nosimplify, -geojson\n\n")
		sys.exit()

	# Get municipality

	municipality_query = sys.argv[1]
	municipality_id, municipality_name = get_municipality(municipality_query)
	message ("Municipality:\t%s %s\n" % (municipality_id, municipality_name))

	# Get topo data category

	for product in ["Topo10", "Topo50", "Topo100", "Topo250"]:
		if "-" + product in sys.argv or "-" + product.lower() in sys.argv:
			topo_product = product
			if product != "Topo10":
				data_categories.remove("hydro")
				data_categories.append("hydrografi")
				data_categories.append("kulturhistorisklamning")
			if topo_product == "Topo250":
				grid_size = 100000  # 100x100 km
				max_combine_members = 2

	message ("Topo dataset:\t%s\n" % topo_product)

	if len(sys.argv) > 2 and not "-" in sys.argv[2]:
		category_input = sys.argv[2].lower().replace("ö", "o").replace("å", "a").replace("ä", "a").replace("ø", "o").replace("æ", "a")
		if topo_product == "Topo10":
			category_input.replace("hydrografi", "hydro")
		else:
			category_input.replace("hydro", "hydrografi")
		data_category = None
		for category in data_categories:
			if category_input in category.lower():
				data_category = category
				break
		if not data_category:
			sys.exit("Data category not recognized: %s\n" % ", ".join(data_categories))
	else:
		data_category = "topo"

	if data_category != "topo":
		message ("Topo category:\t%s\n" % data_category)
	message ("\n")

	if data_category in ["topo", "mark"]:
		token = get_token()

	if data_category != "mark":
		load_municipality_boundary(municipality_id)

	# Get other options

	if "-seanames" in sys.argv:
		add_sea_names = True
	if "-baynames" in sys.argv:
		add_bay_names = True
	if "-wetland" in sys.argv:
		merge_wetland = True
	if "-nosimplify" in sys.argv:
		simplify = False
	if "-debug" in sys.argv:
		debug = True
	if "-tag" in sys.argv or "-tags" in sys.argv:
		topo_tags = True
	if "-geojson" in sys.argv or "-json" in sys.argv:
		json_output = True

	output_filename = "topo_%s_%s" % (municipality_id, municipality_name.replace(" ", "_"))
	if data_category != "topo":
		output_filename += "_" + data_category
	if topo_product != "Topo10":
		output_filename = output_filename.replace("topo", topo_product.lower())
	if debug:
		output_filename += "_debug"

	# Process data

	load_topo_data(municipality_id, municipality_name, data_category)

	if json_output:
		save_geojson(output_filename + ".geojson")
	else:
		if data_category in ["topo", "hydro", "hydrografi"]:
			if get_topo_rivers and topo_product != "Topo250":
				load_topo_rivers()
			combine_rivers()

		create_relations_structure()
		# Note: After this point, segments index should be fixed and feature['coordinates'] may not exactly match member segments.

		if data_category == "topo":
			identify_islands()
			if get_name:
				get_place_names()

		identify_intersections()
		save_osm(output_filename + ".osm")

	duration = time.time() - start_time
	message ("\tTotal run time %s\n\n" % timeformat(duration))
