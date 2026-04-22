# -*- coding: utf-8 -*-
"""
Voxel-Based Urban Microclimate Engine
Author: Firman Afrianto & Maya Safira

QGIS Processing Toolbox script.

Main features:
1. Buildings are processed from footprint polygons, not only visual centroids.
2. Height field / floor field / default height are supported with safe fallbacks.
3. Boundary polygon is actually used for clipping and filtering.
4. Terrain is rendered as a smooth mesh from DEM, not as terrain voxels.
5. Canopy raster is supported for analysis-only or voxel+analysis modes.
6. Vegetation polygons are supported as ground greenery voxels.
7. Landmark layer is supported as a visibility analysis component.
8. Analysis points follow the terrain elevation.
9. Output memory layers are added to QGIS: analysis points and building centroids.
10. Modern web viewer with dashboard, layer toggles, smooth terrain, canopy, and
    optional semi-transparent OSM basemap.
11. Clean output folder: JSON, HTML, and concise reports.

Notes:
- For OSM basemap, the viewer uses static demo tiles disabled by default.
  This keeps the viewer stable.
- This script is intentionally self-contained so it can be pasted directly
  as a Processing script.
"""

import os
import json
import math
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterCrs,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
)


class VoxCityViewer(QgsProcessingAlgorithm):
    BUILDINGS = "BUILDINGS"
    BUILDING_MODE = "BUILDING_MODE"
    HEIGHT_FIELD = "HEIGHT_FIELD"
    FLOOR_FIELD = "FLOOR_FIELD"
    DEFAULT_HEIGHT = "DEFAULT_HEIGHT"
    FLOOR_HEIGHT = "FLOOR_HEIGHT"
    VEGETATION = "VEGETATION"
    CANOPY_RASTER = "CANOPY_RASTER"
    CANOPY_MODE = "CANOPY_MODE"
    MIN_CANOPY_HEIGHT = "MIN_CANOPY_HEIGHT"
    MAX_CANOPY_HEIGHT = "MAX_CANOPY_HEIGHT"
    CANOPY_SAMPLE_STEP = "CANOPY_SAMPLE_STEP"
    LANDMARKS = "LANDMARKS"
    ROADS = "ROADS"
    ROAD_WIDTH_FIELD = "ROAD_WIDTH_FIELD"
    ROAD_DEFAULT_WIDTH = "ROAD_DEFAULT_WIDTH"
    BOUNDARY = "BOUNDARY"
    DEM = "DEM"
    TARGET_CRS = "TARGET_CRS"
    VOXEL_SIZE = "VOXEL_SIZE"
    ANALYSIS_STEP = "ANALYSIS_STEP"
    TERRAIN_STEP = "TERRAIN_STEP"
    VIEW_RADIUS = "VIEW_RADIUS"
    SUN_AZIMUTH = "SUN_AZIMUTH"
    SUN_ALTITUDE = "SUN_ALTITUDE"
    TITLE = "TITLE"
    ADD_QGIS_LAYERS = "ADD_QGIS_LAYERS"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def tr(self, s):
        return QCoreApplication.translate("VoxCityViewer", s)

    def createInstance(self):
        return VoxCityViewer()

    def name(self):
        return "voxcity"

    def displayName(self):
        return "Voxel-Based Urban Microclimate Engine (VUME)"

    def shortHelpString(self):
        return self.tr(
            "<p><b>Created By: Firman Afrianto, Maya Safira</b></p>"
            "<p>Technical validation and debugging support:</b> Evan and Dimas Tri Rendra Graha<b></p>"

            "<p>This tool builds an interactive <b>voxel-based 3D urban analytical viewer</b> from "
            "<b>building footprints</b>, <b>DEM terrain</b>, optional <b>canopy raster</b>, optional "
            "<b>vegetation polygons</b>, and optional <b>landmark layers</b>. "
            "It produces a <b>smooth terrain surface</b>, <b>building / vegetation / canopy voxels</b>, "
            "<b>analysis points</b>, a <b>web-based 3D dashboard</b>, and optional <b>QGIS output layers</b> "
            "for spatial interpretation, design exploration, urban microclimate reading, and decision support. "
            "<br><br><i>Conceptually inspired by the voxel-based urban modeling framework introduced in VoxCity "
            "(Fujiwara et al., 2026), and extended for planning-oriented spatial intelligence and decision-support applications.</i></p>"
            
            "<p><b>Conceptual and interpretation notes</b></p>"
            "<ul>"
            "<li><b>Analytical proxy model</b>: outputs are not direct sensor measurements. They are "
            "computed spatial proxies derived from urban form, terrain, greenery, and visibility context.</li>"
            "<li><b>Decision-support oriented</b>: this tool is intended for planning analysis, research, "
            "scenario communication, teaching, and spatial design exploration.</li>"
            "<li><b>Not a physically rigorous climate simulator</b>: solar, comfort, sky view, green view, "
            "shading, and landmark visibility are proxy indicators rather than full physics-based simulations.</li>"
            "<li><b>Interpret with context</b>: outputs should be interpreted together with local planning rules, "
            "field knowledge, and complementary datasets.</li>"
            "<li><b>Viewer-friendly generalisation</b>: building and canopy volumes are generalized into voxels "
            "to create a responsive and visually interpretable 3D model.</li>"
            "</ul>"

            "<p><b>Inputs</b></p>"
            "<ul>"
            "<li><b>Building footprints</b>: polygon layer used as the main urban mass input</li>"
            "<li><b>Height field</b>: optional numeric field storing building height in meters</li>"
            "<li><b>Floor field</b>: optional numeric field storing number of floors</li>"
            "<li><b>Default height</b>: fallback height when no height / floor attribute is available</li>"
            "<li><b>Floor-to-floor height</b>: conversion factor from floors to meters</li>"
            "<li><b>Boundary polygon</b>: optional clipping boundary for the study area</li>"
            "<li><b>DEM terrain</b>: raster used to build smooth terrain and drape analysis to elevation</li>"
            "<li><b>Vegetation polygon</b>: optional greenery polygons converted into vegetation voxels</li>"
            "<li><b>Canopy raster</b>: optional canopy height model used for greenery analysis and optional canopy voxels</li>"
            "<li><b>Landmark layer</b>: optional point / line / polygon layer used as a visibility reference</li>"
            "<li><b>Target CRS</b>: projected CRS recommended in meter units for stable voxel and terrain behaviour</li>"
            "<li><b>Voxel size</b>: spatial resolution of 3D voxelisation</li>"
            "<li><b>Analysis step</b>: spacing of analytical sampling points</li>"
            "<li><b>Terrain step</b>: DEM sampling step for smooth terrain generation</li>"
            "<li><b>View radius</b>: neighbourhood radius used in proxy-based spatial analysis</li>"
            "<li><b>Sun azimuth and sun altitude</b>: parameters influencing solar and shading proxies</li>"
            "</ul>"

            "<p><b>Height handling logic</b></p>"
            "<ul>"
            "<li>If <b>Height field</b> is available and valid, building height uses that field directly.</li>"
            "<li>If height is missing but <b>Floor field</b> is available, height is estimated as:</li>"
            "</ul>"
            "<pre>height_m = floors * floor_height</pre>"
            "<ul>"
            "<li>If neither field is available, the tool uses <b>Default height</b>.</li>"
            "</ul>"

            "<p><b>Spatial processing logic</b></p>"
            "<ul>"
            "<li>Buildings are transformed into the target CRS and optionally clipped by the boundary.</li>"
            "<li>Terrain is sampled from DEM and rendered as a <b>smooth mesh</b>, not terrain voxels.</li>"
            "<li>Building volumes are voxelised from footprint sampling, not only from centroids.</li>"
            "<li>Vegetation polygons are converted into surface-level greenery voxels.</li>"
            "<li>Canopy raster can be used as <b>analysis only</b> or as <b>voxel + analysis</b>.</li>"
            "<li>Analysis points follow the terrain elevation from the DEM.</li>"
            "<li>Output analysis can optionally be added back into QGIS as memory layers.</li>"
            "</ul>"

            "<p><b>Analytical indicators</b></p>"

            "<p>From version 8 onwards, the four core microclimate indicators are computed as "
            "<b>physical-unit values</b> using established methodology from urban climatology literature, "
            "accelerated via <b>QgsSpatialIndex</b> for tractable performance on large study areas. "
            "Each indicator can be viewed as a 0–1 normalised score (for visual comparison) or as its "
            "physical unit (for citation in reports and papers) via the <b>Score ↔ Physical Unit</b> "
            "toggle in the dashboard.</p>"

            "<p><b>A) Composite</b></p>"
            "<ul>"
            "<li>Weighted integrative score combining the other indicators (0–1)</li>"
            "<li>Weights: Solar 20%, Sky View 25%, Green View 25%, Landmark 15%, Shading 15%</li>"
            "</ul>"

            "<p><b>B) Comfort</b></p>"
            "<ul>"
            "<li>Proxy of microclimate and environmental comfort (0–1)</li>"
            "<li>Weighted: Green View 35%, Shading 30%, Sky View 15%, inverse Solar 20%</li>"
            "</ul>"

            "<p><b>C) Solar — Global Horizontal Irradiance (W/m²)</b></p>"
            "<ul>"
            "<li>Computed using a simplified ASHRAE clear-sky model with SVF modulation.</li>"
            "<li>Formula: GHI = DNI × sin(α) × (1 − shadow_coverage) + DHI × SVF</li>"
            "<li>DNI ≈ 900 W/m² (clear-sky direct normal), DHI ≈ 100 W/m² (diffuse from open sky)</li>"
            "<li>α = sun altitude from input parameter; shadow_coverage from building shadow raycast</li>"
            "<li><i>Reference:</i> Iqbal, M. (1983). An Introduction to Solar Radiation. Academic Press. / ASHRAE Handbook.</li>"
            "</ul>"

            "<p><b>D) Sky View — Sky View Factor (SVF, 0–1)</b></p>"
            "<ul>"
            "<li>Fraction of the sky hemisphere visible from each analytical point.</li>"
            "<li>Computed by ray-casting in <b>36 azimuth sectors</b> (10° resolution).</li>"
            "<li>For each sector, the highest elevation angle β to buildings and canopy is retained.</li>"
            "<li>Canopy uses a porosity factor of 0.65 (allows partial sky penetration through foliage).</li>"
            "<li>Formula: SVF = 1 − (1/N) × Σ sin²(β_i), where N = 36 sectors</li>"
            "<li><i>References:</i> Oke, T.R. (1987). Boundary Layer Climates (2nd ed.). Methuen. / "
            "Johnson, G.T. & Watson, I.D. (1984). The determination of view-factors in urban canyons. "
            "Journal of Climate and Applied Meteorology, 23(2), 329–335.</li>"
            "</ul>"

            "<p><b>E) Green View — Green View Index (GVI, %)</b></p>"
            "<ul>"
            "<li>Percentage of the surrounding horizon that contains vegetation or canopy within the view radius.</li>"
            "<li>Computed as hemispheric GIS adaptation of street-level photo-based GVI.</li>"
            "<li>For each of 36 azimuth sectors, flag whether any vegetation or canopy point is hit within radius.</li>"
            "<li>GVI = (hit sectors / 36) × 100%</li>"
            "<li><i>Reference:</i> Yang, J., Zhao, L., Mcbride, J. &amp; Gong, P. (2009). Can you see green? "
            "Assessing the visibility of urban forests in cities. Landscape and Urban Planning, 91(2), 97–104.</li>"
            "</ul>"

            "<p><b>F) Shading — Shadow Coverage & Length</b></p>"
            "<ul>"
            "<li>Shadow coverage fraction (0–1) and mean shadow length (m) from nearby buildings.</li>"
            "<li>For each building within radius: L = H / tan(α), where H = building height, α = sun altitude.</li>"
            "<li>Point is flagged in shadow if it lies along the anti-sun direction within shadow length L.</li>"
            "<li>Coverage = fraction of buildings casting shadow onto the point.</li>"
            "<li><i>Reference:</i> Ratti, C. &amp; Richens, P. (2004). Raster analysis of urban form. "
            "Environment and Planning B: Planning and Design, 31(2), 297–309.</li>"
            "</ul>"

            "<p><b>G) Landmark</b></p>"
            "<ul>"
            "<li>Proxy of landmark visibility and spatial legibility (0–1)</li>"
            "<li>Depends on distance to landmark attenuated by sky view factor</li>"
            "<li>No established physical unit; retained as decision-support proxy</li>"
            "</ul>"

            "<p><b>Physical-unit fields in QGIS output</b></p>"
            "<ul>"
            "<li><b>svf_val</b>: Sky View Factor (0–1, unitless)</li>"
            "<li><b>gvi_pct</b>: Green View Index (%)</li>"
            "<li><b>ghi_wm2</b>: Global Horizontal Irradiance (W/m²)</li>"
            "<li><b>shadow_frc</b>: Shadow coverage fraction (0–1)</li>"
            "<li><b>shadow_m</b>: Mean shadow length (m)</li>"
            "</ul>"

            "<p><b>What it produces</b></p>"

            "<p><b>A) 3D web viewer outputs</b></p>"
            "<ul>"
            "<li>Smooth terrain mesh from DEM</li>"
            "<li>Voxelised buildings</li>"
            "<li>Vegetation voxels</li>"
            "<li>Optional canopy voxels</li>"
            "<li>Analysis spheres / points</li>"
            "<li>Interactive dashboard with mode switching and layer toggles</li>"
            "</ul>"

            "<p><b>B) Analytical datasets</b></p>"
            "<ul>"
            "<li><b>voxels.json</b>: voxel objects for buildings, vegetation, and canopy</li>"
            "<li><b>analysis.json</b>: analytical point dataset with all proxy indicators</li>"
            "<li><b>terrain.json</b>: sampled terrain grid for smooth surface generation</li>"
            "<li><b>centroids.json</b>: building centroid summary with indicator values</li>"
            "<li><b>summary.json</b>: compact metadata and output summary</li>"
            "</ul>"

            "<p><b>C) QGIS layer outputs</b></p>"
            "<ul>"
            "<li><b>voxcity_analysis_points</b>: memory layer of analytical points</li>"
            "<li><b>voxcity_building_centroids</b>: memory layer of building centroid summaries</li>"
            "</ul>"

            "<p><b>Output datasets</b></p>"
            "<ol>"
            "<li><b>index.html</b> interactive 3D analytical viewer</li>"
            "<li><b>voxels.json</b></li>"
            "<li><b>analysis.json</b></li>"
            "<li><b>terrain.json</b></li>"
            "<li><b>centroids.json</b></li>"
            "<li><b>summary.json</b></li>"
            "<li><b>QGIS memory layers</b> when enabled</li>"
            "</ol>"

            "<p><b>Viewer behaviour</b></p>"
            "<ul>"
            "<li>Buildings are coloured according to the selected active analysis mode.</li>"
            "<li>Analysis points float above terrain following DEM-based elevation.</li>"
            "<li>Legend displays the selected indicator scale from low to high.</li>"
            "<li>Optional OSM basemap is intended as contextual visual background only.</li>"
            "</ul>"

            "<p><b>Important notes</b></p>"
            "<ul>"
            "<li>Use a <b>projected CRS in meters</b> for reliable voxel and terrain geometry.</li>"
            "<li>Smaller voxel size increases visual detail but also increases memory and rendering load.</li>"
            "<li>Smaller terrain step increases smooth terrain detail but may slow export and viewer performance.</li>"
            "<li>Canopy voxel mode can significantly increase voxel count in areas with dense tree cover.</li>"
            "<li>If output is empty, check CRS consistency, boundary coverage, and raster validity.</li>"
            "<li>OSM background in the viewer is a contextual visual aid and may fail if internet access is unavailable.</li>"
            "<li>For research reporting, clearly state that analytical results are <b>proxy indicators</b>.</li>"
            "</ul>"

            "<p><b>Dependencies</b></p>"
            "<ul>"
            "<li><b>QGIS Processing framework</b></li>"
            "<li><b>Three.js CDN</b> for interactive web rendering</li>"
            "<li><b>Valid DEM raster</b> for terrain-aware outputs</li>"
            "<li><b>Optional canopy raster and vegetation polygons</b> for greenery-sensitive analysis</li>"
            "</ul>"
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.BUILDINGS, "Buildings", [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterEnum(self.BUILDING_MODE, "Building render mode", options=["Solid extruded (realistic)", "Voxel (analytical)"], defaultValue=0))
        self.addParameter(QgsProcessingParameterField(self.HEIGHT_FIELD, "Height field (optional)", parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterField(self.FLOOR_FIELD, "Floor field (optional)", parentLayerParameterName=self.BUILDINGS, type=QgsProcessingParameterField.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.DEFAULT_HEIGHT, "Default height (m)", QgsProcessingParameterNumber.Double, defaultValue=8.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(self.FLOOR_HEIGHT, "Floor-to-floor height (m)", QgsProcessingParameterNumber.Double, defaultValue=3.5, minValue=2.0))
        self.addParameter(QgsProcessingParameterFeatureSource(self.VEGETATION, "Vegetation polygon (optional)", [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.CANOPY_RASTER, "Canopy raster (optional)", optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.CANOPY_MODE, "Canopy mode", options=["Analysis only", "Voxel + analysis"], defaultValue=1))
        self.addParameter(QgsProcessingParameterNumber(self.MIN_CANOPY_HEIGHT, "Min canopy height (m)", QgsProcessingParameterNumber.Double, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.MAX_CANOPY_HEIGHT, "Max canopy height cap (m)", QgsProcessingParameterNumber.Double, defaultValue=35.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(self.CANOPY_SAMPLE_STEP, "Canopy sample step", QgsProcessingParameterNumber.Double, defaultValue=20.0, minValue=2.0))
        self.addParameter(QgsProcessingParameterFeatureSource(self.LANDMARKS, "Landmark layer (optional)", [QgsProcessing.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(self.ROADS, "Roads layer (line, optional)", [QgsProcessing.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterField(self.ROAD_WIDTH_FIELD, "Road width field (optional, meters)", parentLayerParameterName=self.ROADS, type=QgsProcessingParameterField.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.ROAD_DEFAULT_WIDTH, "Default road width (m)", QgsProcessingParameterNumber.Double, defaultValue=6.0, minValue=0.5))
        self.addParameter(QgsProcessingParameterFeatureSource(self.BOUNDARY, "Boundary (optional)", [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.DEM, "DEM terrain"))
        self.addParameter(QgsProcessingParameterCrs(self.TARGET_CRS, "Target CRS", defaultValue="EPSG:3857"))
        self.addParameter(QgsProcessingParameterNumber(self.VOXEL_SIZE, "Voxel size", QgsProcessingParameterNumber.Double, defaultValue=10.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(self.ANALYSIS_STEP, "Analysis step", QgsProcessingParameterNumber.Double, defaultValue=80.0, minValue=5.0))
        self.addParameter(QgsProcessingParameterNumber(self.TERRAIN_STEP, "Terrain step", QgsProcessingParameterNumber.Double, defaultValue=20.0, minValue=2.0))
        self.addParameter(QgsProcessingParameterNumber(self.VIEW_RADIUS, "View radius", QgsProcessingParameterNumber.Double, defaultValue=250.0, minValue=20.0))
        self.addParameter(QgsProcessingParameterNumber(self.SUN_AZIMUTH, "Sun azimuth", QgsProcessingParameterNumber.Double, defaultValue=135.0, minValue=0.0, maxValue=360.0))
        self.addParameter(QgsProcessingParameterNumber(self.SUN_ALTITUDE, "Sun altitude", QgsProcessingParameterNumber.Double, defaultValue=45.0, minValue=1.0, maxValue=89.0))
        self.addParameter(QgsProcessingParameterString(self.TITLE, "Viewer title", defaultValue="Voxel-Based Urban Microclimate Engine"))
        self.addParameter(QgsProcessingParameterBoolean(self.ADD_QGIS_LAYERS, "Add output layers to QGIS", defaultValue=True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, "Output folder"))

    def processAlgorithm(self, parameters, context, feedback):
        bs = self.parameterAsSource(parameters, self.BUILDINGS, context)
        if bs is None:
            raise QgsProcessingException("Building layer is required.")

        dem = self.parameterAsRasterLayer(parameters, self.DEM, context)
        if dem is None:
            raise QgsProcessingException("DEM terrain is required.")

        veg_src = self.parameterAsSource(parameters, self.VEGETATION, context)
        canopy_raster = self.parameterAsRasterLayer(parameters, self.CANOPY_RASTER, context)
        landmarks_src = self.parameterAsSource(parameters, self.LANDMARKS, context)
        roads_src = self.parameterAsSource(parameters, self.ROADS, context)
        road_width_field = self.parameterAsString(parameters, self.ROAD_WIDTH_FIELD, context)
        road_default_width = self.parameterAsDouble(parameters, self.ROAD_DEFAULT_WIDTH, context)
        boundary_src = self.parameterAsSource(parameters, self.BOUNDARY, context)

        tcrs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        vsz = self.parameterAsDouble(parameters, self.VOXEL_SIZE, context)
        astep = self.parameterAsDouble(parameters, self.ANALYSIS_STEP, context)
        tstep = self.parameterAsDouble(parameters, self.TERRAIN_STEP, context)
        vradius = self.parameterAsDouble(parameters, self.VIEW_RADIUS, context)
        saz = self.parameterAsDouble(parameters, self.SUN_AZIMUTH, context)
        sal = self.parameterAsDouble(parameters, self.SUN_ALTITUDE, context)
        title = self.parameterAsString(parameters, self.TITLE, context)
        add_layers = self.parameterAsBool(parameters, self.ADD_QGIS_LAYERS, context)
        out = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        height_field = self.parameterAsString(parameters, self.HEIGHT_FIELD, context)
        floor_field = self.parameterAsString(parameters, self.FLOOR_FIELD, context)
        default_height = self.parameterAsDouble(parameters, self.DEFAULT_HEIGHT, context)
        floor_height = self.parameterAsDouble(parameters, self.FLOOR_HEIGHT, context)
        canopy_mode = self.parameterAsEnum(parameters, self.CANOPY_MODE, context)
        building_mode = self.parameterAsEnum(parameters, self.BUILDING_MODE, context)  # 0=solid, 1=voxel
        min_canopy_h = self.parameterAsDouble(parameters, self.MIN_CANOPY_HEIGHT, context)
        max_canopy_h = self.parameterAsDouble(parameters, self.MAX_CANOPY_HEIGHT, context)
        canopy_step = self.parameterAsDouble(parameters, self.CANOPY_SAMPLE_STEP, context)

        out.mkdir(parents=True, exist_ok=True)

        feedback.pushInfo("Preparing transforms...")
        bxf = QgsCoordinateTransform(bs.sourceCrs(), tcrs, QgsProject.instance())

        boundary_geom = None
        if boundary_src:
            feedback.pushInfo("Reading boundary...")
            bnd_xf = QgsCoordinateTransform(boundary_src.sourceCrs(), tcrs, QgsProject.instance())
            bnd_geoms = []
            for f in boundary_src.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isEmpty():
                    continue
                g.transform(bnd_xf)
                bnd_geoms.append(g)
            if bnd_geoms:
                boundary_geom = QgsGeometry.unaryUnion(bnd_geoms)

        feedback.pushInfo("Transforming buildings...")
        buildings = []
        for f in bs.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            try:
                g.transform(bxf)
            except Exception:
                continue

            if boundary_geom:
                if not g.intersects(boundary_geom):
                    continue
                g = g.intersection(boundary_geom)
                if g.isEmpty():
                    continue

            h = default_height
            try:
                if height_field:
                    v = f[height_field]
                    if v is not None and str(v).strip() != "":
                        h = float(v)
                elif floor_field:
                    v = f[floor_field]
                    if v is not None and str(v).strip() != "":
                        h = float(v) * float(floor_height)
            except Exception:
                h = default_height
            h = max(1.0, float(h))

            try:
                c = g.centroid().asPoint()
            except Exception:
                continue

            buildings.append({
                "geom": g,
                "h": h,
                "cx": c.x(),
                "cy": c.y(),
            })

        if not buildings:
            raise QgsProcessingException("No valid buildings found after transform/filter/clip.")

        ext = buildings[0]["geom"].boundingBox()
        for b in buildings[1:]:
            ext.combineExtentWith(b["geom"].boundingBox())
        if boundary_geom:
            ext.combineExtentWith(boundary_geom.boundingBox())

        cx = (ext.xMinimum() + ext.xMaximum()) / 2.0
        cy = (ext.yMinimum() + ext.yMaximum()) / 2.0

        # Compute WGS84 georeference for the web viewer minimap
        feedback.pushInfo("Computing WGS84 georeference for minimap...")
        from qgis.core import QgsCoordinateReferenceSystem
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        to_wgs84 = QgsCoordinateTransform(tcrs, wgs84, QgsProject.instance())
        try:
            center_ll = to_wgs84.transform(QgsPointXY(cx, cy))
            sw_ll = to_wgs84.transform(QgsPointXY(ext.xMinimum(), ext.yMinimum()))
            ne_ll = to_wgs84.transform(QgsPointXY(ext.xMaximum(), ext.yMaximum()))
            nw_ll = to_wgs84.transform(QgsPointXY(ext.xMinimum(), ext.yMaximum()))
            se_ll = to_wgs84.transform(QgsPointXY(ext.xMaximum(), ext.yMinimum()))
            geo_ref = {
                "center": [round(center_ll.y(), 7), round(center_ll.x(), 7)],  # [lat, lon]
                "bounds": [
                    [round(sw_ll.y(), 7), round(sw_ll.x(), 7)],
                    [round(ne_ll.y(), 7), round(ne_ll.x(), 7)],
                ],
                "corners": {
                    "sw": [round(sw_ll.y(), 7), round(sw_ll.x(), 7)],
                    "nw": [round(nw_ll.y(), 7), round(nw_ll.x(), 7)],
                    "ne": [round(ne_ll.y(), 7), round(ne_ll.x(), 7)],
                    "se": [round(se_ll.y(), 7), round(se_ll.x(), 7)],
                },
                "cx": cx,
                "cy": cy,
                "target_crs": tcrs.authid(),
                "valid": True,
            }
        except Exception as e:
            feedback.pushInfo("WGS84 transform failed, minimap will be disabled: {}".format(e))
            geo_ref = {"valid": False}

        # Helper closure to project local (lx, ly) back to [lat, lon]
        def local_to_lonlat(lx, ly):
            if not geo_ref.get("valid"):
                return None
            try:
                pll = to_wgs84.transform(QgsPointXY(lx + cx, ly + cy))
                return [round(pll.y(), 7), round(pll.x(), 7)]
            except Exception:
                return None

        feedback.pushInfo("Reading vegetation...")
        vegetation = self._read_polygons(veg_src, tcrs, boundary_geom) if veg_src else []

        feedback.pushInfo("Reading landmarks...")
        landmarks = self._read_landmarks(landmarks_src, tcrs, boundary_geom) if landmarks_src else []

        feedback.pushInfo("Reading roads...")
        roads = self._read_roads(roads_src, tcrs, boundary_geom, road_width_field, road_default_width, cx, cy, local_to_lonlat) if roads_src else []

        feedback.pushInfo("Sampling terrain...")
        terrain = self.sampleTerrain(dem, tcrs, ext, tstep)

        feedback.pushInfo("Sampling canopy...")
        canopy_samples = []
        if canopy_raster:
            canopy_samples = self.sampleCanopy(canopy_raster, tcrs, ext, canopy_step, min_canopy_h, max_canopy_h, boundary_geom, cx, cy)

        feedback.pushInfo("Building spatial indexes for accelerated ray-casting...")
        from qgis.core import QgsSpatialIndex, QgsFeature as QgsFeat
        # Index buildings by centroid for neighborhood queries
        b_index = QgsSpatialIndex()
        b_lookup = {}  # id -> building dict
        for i, b in enumerate(buildings):
            feat = QgsFeat()
            feat.setId(i)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(b["cx"], b["cy"])))
            b_index.insertFeature(feat)
            b_lookup[i] = b
        # Index vegetation by centroid
        v_index = QgsSpatialIndex()
        v_lookup = {}
        for i, v in enumerate(vegetation):
            try:
                c = v["geom"].centroid().asPoint()
            except Exception:
                continue
            feat = QgsFeat()
            feat.setId(i)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(c.x(), c.y())))
            v_index.insertFeature(feat)
            v_lookup[i] = {"x": c.x(), "y": c.y(), "geom": v["geom"]}
        # Index canopy samples
        c_index = QgsSpatialIndex()
        c_lookup = {}
        for i, cs in enumerate(canopy_samples):
            feat = QgsFeat()
            feat.setId(i)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(cs["x"], cs["y"])))
            c_index.insertFeature(feat)
            c_lookup[i] = cs

        indexes = {"b": (b_index, b_lookup), "v": (v_index, v_lookup), "c": (c_index, c_lookup)}

        feedback.pushInfo("Running analysis with physical-unit ray-casting...")
        analysis = []
        x = ext.xMinimum()
        while x <= ext.xMaximum():
            y = ext.yMinimum()
            while y <= ext.yMaximum():
                if boundary_geom and not self._point_in_boundary(x, y, boundary_geom):
                    y += astep
                    continue

                ground = self.sampleDEM(dem, tcrs, x, y)
                ap = self.computeAdvancedScore(x, y, ground, buildings, vegetation, canopy_samples, landmarks, vradius, saz, sal, indexes)
                lx = x - cx
                ly = y - cy
                analysis.append({
                    "x": lx,
                    "y": ly,
                    "z": ground,
                    "ll": local_to_lonlat(lx, ly),
                    "composite": ap["composite"],
                    "comfort": ap["comfort"],
                    "solar": ap["solar"],
                    "skyview": ap["skyview"],
                    "greenview": ap["greenview"],
                    "shading": ap["shading"],
                    "landmark": ap["landmark"],
                    # Physical-unit values for citation and reporting
                    "svf_val": ap["svf_val"],           # Sky View Factor (unitless 0-1, Oke 1987)
                    "gvi_val": ap["gvi_val"],           # Green View Index (% 0-100, Yang 2009)
                    "ghi_val": ap["ghi_val"],           # Global Horizontal Irradiance (W/m2, instantaneous)
                    "shadow_val": ap["shadow_val"],     # Shadow coverage fraction (0-1)
                    "shadow_m": ap["shadow_m"],         # Mean shadow length (m) from nearby buildings
                })
                y += astep
            x += astep

        analysis_lookup = self._build_analysis_lookup(analysis, astep)

        feedback.pushInfo("Building voxels from footprint sampling...")
        voxels = []
        solids = []
        centroids = []
        for b in buildings:
            base = self.sampleDEM(dem, tcrs, b["cx"], b["cy"])
            lx = b["cx"] - cx
            ly = b["cy"] - cy
            score = analysis_lookup(lx, ly)
            centroids.append({
                "x": lx,
                "y": ly,
                "z": base,
                "ll": local_to_lonlat(lx, ly),
                "height": b["h"],
                "composite": score["composite"],
                "comfort": score["comfort"],
                "solar": score["solar"],
                "skyview": score["skyview"],
                "greenview": score["greenview"],
                "shading": score["shading"],
                "landmark": score["landmark"],
                "svf_val": score.get("svf_val", 0),
                "gvi_val": score.get("gvi_val", 0),
                "ghi_val": score.get("ghi_val", 0),
                "shadow_val": score.get("shadow_val", 0),
                "shadow_m": score.get("shadow_m", 0),
            })
            if building_mode == 0:
                # Solid extruded mode - export polygon rings + height
                solid = self._extract_building_solid(b["geom"], b["h"], cx, cy, base, score, local_to_lonlat)
                if solid:
                    solids.append(solid)
            else:
                # Voxel mode - original behaviour
                voxels.extend(self._voxelize_building_footprint(b["geom"], b["h"], vsz, cx, cy, base, score))

        feedback.pushInfo("Building vegetation voxels...")
        veg_voxels = self._voxelize_vegetation(vegetation, vsz, cx, cy, dem, tcrs, boundary_geom)
        voxels.extend(veg_voxels)

        canopy_voxels = []
        if canopy_mode == 1 and canopy_samples:
            feedback.pushInfo("Building canopy voxels...")
            canopy_voxels = self._voxelize_canopy(canopy_samples, vsz)
            voxels.extend(canopy_voxels)

        feedback.pushInfo("Saving outputs...")
        summary = {
            "title": title,
            "building_mode": "solid" if building_mode == 0 else "voxel",
            "building_count": len(buildings),
            "solid_count": len(solids),
            "analysis_count": len(analysis),
            "voxel_count": len(voxels),
            "vegetation_count": len(vegetation),
            "canopy_sample_count": len(canopy_samples),
            "canopy_voxel_count": len(canopy_voxels),
            "landmark_count": len(landmarks),
            "road_count": len(roads),
            "target_crs": tcrs.authid(),
            "terrain_step": tstep,
            "analysis_step": astep,
            "voxel_size": vsz,
        }

        (out / "voxels.json").write_text(json.dumps(voxels, ensure_ascii=False), encoding="utf-8")
        (out / "solids.json").write_text(json.dumps(solids, ensure_ascii=False), encoding="utf-8")
        (out / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        (out / "terrain.json").write_text(json.dumps(terrain, ensure_ascii=False), encoding="utf-8")
        (out / "centroids.json").write_text(json.dumps(centroids, ensure_ascii=False), encoding="utf-8")
        (out / "roads.json").write_text(json.dumps(roads, ensure_ascii=False), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "index.html").write_text(self.buildHTML(title, voxels, solids, roads, analysis, terrain, tstep, building_mode, geo_ref, canopy_samples), encoding="utf-8")

        if add_layers:
            feedback.pushInfo("Adding layers to QGIS...")
            self.addAnalysisLayer(analysis, tcrs, cx, cy)
            self.addCentroidLayer(centroids, tcrs, cx, cy)

        feedback.pushInfo("DONE")
        return {self.OUTPUT_FOLDER: str(out)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _point_in_boundary(self, x, y, boundary_geom):
        try:
            return boundary_geom.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        except Exception:
            return False

    def _read_polygons(self, source, tcrs, boundary_geom):
        xf = QgsCoordinateTransform(source.sourceCrs(), tcrs, QgsProject.instance())
        items = []
        for f in source.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            try:
                g.transform(xf)
            except Exception:
                continue
            if boundary_geom:
                if not g.intersects(boundary_geom):
                    continue
                g = g.intersection(boundary_geom)
                if g.isEmpty():
                    continue
            items.append({"geom": g})
        return items

    def _read_landmarks(self, source, tcrs, boundary_geom):
        xf = QgsCoordinateTransform(source.sourceCrs(), tcrs, QgsProject.instance())
        items = []
        for f in source.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            try:
                g.transform(xf)
            except Exception:
                continue
            if boundary_geom and not g.intersects(boundary_geom):
                continue
            try:
                c = g.centroid().asPoint()
                items.append({"x": c.x(), "y": c.y()})
            except Exception:
                continue
        return items

    def _read_roads(self, source, tcrs, boundary_geom, width_field, default_width, cx, cy, local_to_lonlat):
        """
        Read road line geometries, clip to boundary, densify into polylines in local coords.
        Returns list of {"pts": [[x,y],...], "width": w, "pts_ll": [[lat,lon],...]}.
        """
        xf = QgsCoordinateTransform(source.sourceCrs(), tcrs, QgsProject.instance())
        roads = []
        for f in source.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            try:
                g.transform(xf)
            except Exception:
                continue
            if boundary_geom:
                if not g.intersects(boundary_geom):
                    continue
                g = g.intersection(boundary_geom)
                if g.isEmpty():
                    continue

            # Resolve width
            w = float(default_width)
            try:
                if width_field:
                    v = f[width_field]
                    if v is not None and str(v).strip() != "":
                        w = float(v)
            except Exception:
                w = float(default_width)
            w = max(0.5, w)

            # Extract polylines (handle single/multi)
            try:
                if g.isMultipart():
                    parts = g.asMultiPolyline()
                else:
                    parts = [g.asPolyline()]
            except Exception:
                continue

            for part in parts:
                if not part or len(part) < 2:
                    continue
                pts = []
                pts_ll = []
                for pt in part:
                    try:
                        lx = round(pt.x() - cx, 3)
                        ly = round(pt.y() - cy, 3)
                        pts.append([lx, ly])
                        if local_to_lonlat:
                            ll = local_to_lonlat(lx, ly)
                            if ll:
                                pts_ll.append(ll)
                    except Exception:
                        continue
                if len(pts) < 2:
                    continue
                road_obj = {"pts": pts, "width": round(w, 2)}
                if pts_ll:
                    road_obj["pts_ll"] = pts_ll
                roads.append(road_obj)
        return roads

    # ------------------------------------------------------------------
    # Terrain and canopy
    # ------------------------------------------------------------------

    def sampleTerrain(self, dem, tcrs, ext, step):
        prov = dem.dataProvider()
        dcrs = dem.crs()
        inv = QgsCoordinateTransform(tcrs, dcrs, QgsProject.instance()) if dcrs != tcrs else None
        grid = []
        x = ext.xMinimum()
        while x <= ext.xMaximum():
            row = []
            y = ext.yMinimum()
            while y <= ext.yMaximum():
                pt = QgsPointXY(x, y)
                sp = inv.transform(pt) if inv else pt
                val, ok = prov.sample(sp, 1)
                if ok and val is not None:
                    try:
                        row.append(float(val))
                    except Exception:
                        row.append(0.0)
                else:
                    row.append(0.0)
                y += step
            grid.append(row)
            x += step
        return grid

    def sampleDEM(self, dem, tcrs, x, y):
        prov = dem.dataProvider()
        dcrs = dem.crs()
        inv = QgsCoordinateTransform(tcrs, dcrs, QgsProject.instance()) if dcrs != tcrs else None
        pt = QgsPointXY(x, y)
        sp = inv.transform(pt) if inv else pt
        val, ok = prov.sample(sp, 1)
        if ok and val is not None:
            try:
                return float(val)
            except Exception:
                return 0.0
        return 0.0

    def sampleCanopy(self, raster, tcrs, ext, step, minh, maxh, boundary_geom, cx, cy):
        prov = raster.dataProvider()
        rcrs = raster.crs()
        inv = QgsCoordinateTransform(tcrs, rcrs, QgsProject.instance()) if rcrs != tcrs else None
        samples = []
        x = ext.xMinimum()
        while x <= ext.xMaximum():
            y = ext.yMinimum()
            while y <= ext.yMaximum():
                if boundary_geom and not self._point_in_boundary(x, y, boundary_geom):
                    y += step
                    continue
                pt = QgsPointXY(x, y)
                sp = inv.transform(pt) if inv else pt
                val, ok = prov.sample(sp, 1)
                if ok and val is not None:
                    try:
                        h = float(val)
                        if math.isfinite(h) and h >= minh:
                            samples.append({
                                "x": x,
                                "y": y,
                                "lx": x - cx,
                                "ly": y - cy,
                                "h": min(h, maxh),
                            })
                    except Exception:
                        pass
                y += step
            x += step
        return samples

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def computeAdvancedScore(self, x, y, ground, buildings, vegetation, canopy_samples, landmarks, radius, saz, sal, indexes=None):
        """
        Compute physical-unit indicators via ray-casting with spatial index acceleration.

        Methodology references:
        - SVF: Oke (1987) "Boundary Layer Climates"; Johnson & Watson (1984)
          "The determination of view-factors in urban canyons" JCAM 23:329-335
        - GVI: Yang, Li, Yang, Lo (2009) "Can you see green? Assessing the
          visibility of urban forests in cities" LUP 91:97-104
        - GHI: ASHRAE Clear-Sky Model; Iqbal (1983) "An Introduction to Solar Radiation"
        - Shadow: Ratti & Richens (2004) "Raster analysis of urban form"
          Environment and Planning B 31:297-309
        """
        r2 = radius * radius
        sf = math.sin(math.radians(sal))  # sun elevation fraction

        # ========= SPATIAL INDEX LOOKUP =========
        # Use QgsSpatialIndex for O(log n) neighborhood retrieval instead of O(n) full scan
        near_buildings = buildings
        near_vegetation_pts = [{"x": v["geom"].centroid().asPoint().x(),
                                 "y": v["geom"].centroid().asPoint().y()}
                                for v in vegetation] if vegetation else []
        near_canopy = canopy_samples

        if indexes:
            from qgis.core import QgsRectangle
            rect = QgsRectangle(x - radius, y - radius, x + radius, y + radius)
            b_index, b_lookup = indexes.get("b", (None, {}))
            v_index, v_lookup = indexes.get("v", (None, {}))
            c_index, c_lookup = indexes.get("c", (None, {}))
            if b_index:
                ids = b_index.intersects(rect)
                near_buildings = [b_lookup[i] for i in ids if i in b_lookup]
            if v_index:
                ids = v_index.intersects(rect)
                near_vegetation_pts = [{"x": v_lookup[i]["x"], "y": v_lookup[i]["y"]}
                                        for i in ids if i in v_lookup]
            if c_index:
                ids = c_index.intersects(rect)
                near_canopy = [c_lookup[i] for i in ids if i in c_lookup]

        # ========= SKY VIEW FACTOR (Oke 1987, Johnson & Watson 1984) =========
        # SVF = 1 - (1/N) * sum(sin^2(beta_i)) where beta_i is elevation angle
        # to tallest obstruction in azimuth sector i. N = 36 (sectors of 10 deg).
        N_AZIMUTH = 36
        sector_deg = 360.0 / N_AZIMUTH
        max_beta_per_sector = [0.0] * N_AZIMUTH  # elevation angle in radians

        # Buildings: contribute elevation angle beta = atan(H / dist)
        for b in near_buildings:
            dx = b["cx"] - x
            dy = b["cy"] - y
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-3 or d > radius:
                continue
            az = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
            sec = int(az / sector_deg) % N_AZIMUTH
            # Height above ground at this point
            h_above = max(0.0, b["h"] - 0)  # assume building base ~= local ground
            beta = math.atan2(h_above, d)
            if beta > max_beta_per_sector[sec]:
                max_beta_per_sector[sec] = beta

        # Canopy: contribute lower obstruction (0.65 weight - canopy is porous)
        for cs in near_canopy:
            dx = cs["x"] - x
            dy = cs["y"] - y
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-3 or d > radius:
                continue
            az = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
            sec = int(az / sector_deg) % N_AZIMUTH
            beta = math.atan2(cs["h"] * 0.65, d)  # canopy porosity factor
            if beta > max_beta_per_sector[sec]:
                max_beta_per_sector[sec] = beta

        svf_val = 1.0 - sum(math.sin(b) ** 2 for b in max_beta_per_sector) / N_AZIMUTH
        svf_val = max(0.0, min(1.0, svf_val))

        # ========= GREEN VIEW INDEX (Yang 2009 adapted for GIS) =========
        # % of azimuth sectors that hit vegetation/canopy within radius.
        # Original Yang uses street-level photos; this is hemispheric GIS proxy.
        green_hit_sectors = [False] * N_AZIMUTH
        for vp in near_vegetation_pts:
            dx = vp["x"] - x
            dy = vp["y"] - y
            d2 = dx * dx + dy * dy
            if d2 > r2 or d2 < 1e-3:
                continue
            az = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
            sec = int(az / sector_deg) % N_AZIMUTH
            green_hit_sectors[sec] = True
        for cs in near_canopy:
            dx = cs["x"] - x
            dy = cs["y"] - y
            d2 = dx * dx + dy * dy
            if d2 > r2 or d2 < 1e-3:
                continue
            az = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
            sec = int(az / sector_deg) % N_AZIMUTH
            green_hit_sectors[sec] = True

        gvi_val = sum(1 for g in green_hit_sectors if g) / N_AZIMUTH * 100.0  # percent

        # ========= SHADOW LENGTH & COVERAGE (Ratti & Richens 2004) =========
        # Shadow coverage: fraction of nearby buildings casting shadow onto this point.
        # Shadow length L = H / tan(alpha) where alpha = sun altitude.
        # Point is shaded if it lies within shadow footprint of a building.
        sun_az_rad = math.radians(saz)
        shadow_dir_x = -math.sin(sun_az_rad)  # opposite of sun direction
        shadow_dir_y = -math.cos(sun_az_rad)
        tan_alpha = math.tan(math.radians(sal)) if sal > 0.5 else 0.01
        shadow_hits = 0
        shadow_len_acc = 0.0
        n_check = 0
        for b in near_buildings:
            dx = x - b["cx"]
            dy = y - b["cy"]
            d = math.sqrt(dx * dx + dy * dy)
            if d > radius:
                continue
            n_check += 1
            # Maximum shadow length from this building
            L = b["h"] / tan_alpha
            shadow_len_acc += L
            # Is this point in the shadow? (along -sun direction from building)
            # Project (dx, dy) onto shadow direction
            proj = dx * shadow_dir_x + dy * shadow_dir_y
            perp = abs(dx * (-shadow_dir_y) + dy * shadow_dir_x)
            if proj > 0 and proj <= L and perp < max(3.0, b["h"] * 0.3):
                shadow_hits += 1

        shadow_val = min(1.0, shadow_hits / max(1, min(n_check, 20)))
        shadow_m = shadow_len_acc / n_check if n_check else 0.0

        # ========= GLOBAL HORIZONTAL IRRADIANCE (ASHRAE/Iqbal) =========
        # Simplified clear-sky model, instantaneous value at sun position saz/sal.
        # GHI = DNI * sin(alpha) + DHI (diffuse)
        # Clear-sky DNI approx 900 W/m2 at high sun; DHI approx 100 W/m2.
        # Shading and SVF modulate the two components separately.
        DNI_CLEAR = 900.0  # W/m2 direct normal at clear noon
        DHI_CLEAR = 100.0  # W/m2 diffuse from open sky
        beam_available = sf if sf > 0 else 0.0
        direct_component = DNI_CLEAR * beam_available * (1.0 - shadow_val)
        diffuse_component = DHI_CLEAR * svf_val
        ghi_val = max(0.0, direct_component + diffuse_component)

        # ========= DERIVE 0-1 SCORES from physical values (backward compat) =========
        skyview = svf_val  # SVF already 0-1
        greenview = gvi_val / 100.0  # GVI% -> 0-1
        shading = shadow_val
        # Solar: normalize to typical noon peak ~1000 W/m2
        solar = max(0.0, min(1.0, ghi_val / 1000.0))

        # Landmark still proxy-based (no established physical unit)
        landmark = 0.0
        if landmarks:
            best = 0.0
            for lm in landmarks:
                dx = lm["x"] - x
                dy = lm["y"] - y
                d = math.sqrt(dx * dx + dy * dy)
                if d <= radius * 4.0:
                    s_score = (1.0 - min(1.0, d / (radius * 4.0))) * skyview
                    if s_score > best:
                        best = s_score
            landmark = best

        # Comfort & composite: weighted combinations (literature-guided)
        comfort = max(0.0, min(1.0,
            greenview * 0.35 + shading * 0.30 + skyview * 0.15 + (1.0 - solar) * 0.20))
        composite = max(0.0, min(1.0,
            solar * 0.20 + skyview * 0.25 + greenview * 0.25 + landmark * 0.15 + shading * 0.15))

        return {
            # Normalized scores 0-1 (for visual coloring, backward compat)
            "composite": round(composite, 4),
            "comfort": round(comfort, 4),
            "solar": round(solar, 4),
            "skyview": round(skyview, 4),
            "greenview": round(greenview, 4),
            "shading": round(shading, 4),
            "landmark": round(landmark, 4),
            # Physical-unit values (for citation in reports/papers)
            "svf_val": round(svf_val, 4),       # unitless 0-1
            "gvi_val": round(gvi_val, 2),       # percent 0-100
            "ghi_val": round(ghi_val, 1),       # W/m2
            "shadow_val": round(shadow_val, 4), # fraction 0-1
            "shadow_m": round(shadow_m, 2),     # meters
        }

    def _build_analysis_lookup(self, analysis, step):
        idx = {}
        for a in analysis:
            gx = int(round(a["x"] / step))
            gy = int(round(a["y"] / step))
            idx[(gx, gy)] = a

        def lookup(lx, ly):
            gx = int(round(lx / step))
            gy = int(round(ly / step))
            if (gx, gy) in idx:
                return idx[(gx, gy)]
            best = None
            dist_best = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cand = idx.get((gx + dx, gy + dy))
                    if cand is not None:
                        d = dx * dx + dy * dy
                        if dist_best is None or d < dist_best:
                            dist_best = d
                            best = cand
            if best:
                return best
            return {
                "composite": 0.0,
                "comfort": 0.0,
                "solar": 0.0,
                "skyview": 0.0,
                "greenview": 0.0,
                "shading": 0.0,
                "landmark": 0.0,
                "svf_val": 0.0,
                "gvi_val": 0.0,
                "ghi_val": 0.0,
                "shadow_val": 0.0,
                "shadow_m": 0.0,
            }

        return lookup

    # ------------------------------------------------------------------
    # Voxel building and canopy
    # ------------------------------------------------------------------

    def _voxelize_building_footprint(self, geom, height, vsz, cx, cy, base, score):
        voxels = []
        bb = geom.boundingBox()
        x0 = math.floor(bb.xMinimum() / vsz) * vsz
        x1 = math.ceil(bb.xMaximum() / vsz) * vsz
        y0 = math.floor(bb.yMinimum() / vsz) * vsz
        y1 = math.ceil(bb.yMaximum() / vsz) * vsz
        zlevels = max(1, int(math.ceil(height / vsz)))

        created = 0
        x = x0
        while x <= x1:
            y = y0
            while y <= y1:
                px = x + vsz / 2.0
                py = y + vsz / 2.0
                if geom.contains(QgsGeometry.fromPointXY(QgsPointXY(px, py))):
                    for zi in range(zlevels):
                        voxels.append({
                            "x": px - cx,
                            "y": py - cy,
                            "z": base + zi * vsz,
                            "type": "building",
                            "composite": score["composite"],
                            "comfort": score["comfort"],
                            "solar": score["solar"],
                            "skyview": score["skyview"],
                            "greenview": score["greenview"],
                            "shading": score["shading"],
                            "landmark": score["landmark"],
                            "svf_val": score.get("svf_val", 0),
                            "gvi_val": score.get("gvi_val", 0),
                            "ghi_val": score.get("ghi_val", 0),
                            "shadow_val": score.get("shadow_val", 0),
                            "shadow_m": score.get("shadow_m", 0),
                        })
                        created += 1
                y += vsz
            x += vsz

        if created == 0:
            c = geom.centroid().asPoint()
            for zi in range(zlevels):
                voxels.append({
                    "x": c.x() - cx,
                    "y": c.y() - cy,
                    "z": base + zi * vsz,
                    "type": "building",
                    "composite": score["composite"],
                    "comfort": score["comfort"],
                    "solar": score["solar"],
                    "skyview": score["skyview"],
                    "greenview": score["greenview"],
                    "shading": score["shading"],
                    "landmark": score["landmark"],
                    "svf_val": score.get("svf_val", 0),
                    "gvi_val": score.get("gvi_val", 0),
                    "ghi_val": score.get("ghi_val", 0),
                    "shadow_val": score.get("shadow_val", 0),
                    "shadow_m": score.get("shadow_m", 0),
                })
        return voxels

    def _extract_building_solid(self, geom, height, cx, cy, base, score, local_to_lonlat=None):
        """
        Extract polygon rings (outer + holes) from building geometry for
        three.js ExtrudeGeometry. Handles single and multi-part polygons.
        Coordinates are translated to local (x - cx, y - cy) space.
        If local_to_lonlat callback is supplied, also attaches lon/lat rings for map display.
        Returns a dict: {"parts": [...], "h": ..., "base": ..., "score": ..., "ll_center": [lat,lon]}
        """
        try:
            if geom.isMultipart():
                polys = geom.asMultiPolygon()
            else:
                polys = [geom.asPolygon()]
        except Exception:
            return None

        parts = []
        for poly in polys:
            if not poly:
                continue
            outer_ring = poly[0] if len(poly) > 0 else None
            if not outer_ring or len(outer_ring) < 3:
                continue

            outer = []
            outer_ll = []
            for pt in outer_ring:
                try:
                    lx = round(pt.x() - cx, 3)
                    ly = round(pt.y() - cy, 3)
                    outer.append([lx, ly])
                    if local_to_lonlat:
                        ll = local_to_lonlat(lx, ly)
                        if ll:
                            outer_ll.append(ll)
                except Exception:
                    continue

            if len(outer) >= 2 and outer[0] == outer[-1]:
                outer = outer[:-1]
            if len(outer_ll) >= 2 and outer_ll[0] == outer_ll[-1]:
                outer_ll = outer_ll[:-1]

            if len(outer) < 3:
                continue

            holes = []
            for ring in poly[1:]:
                if not ring or len(ring) < 3:
                    continue
                hring = []
                for pt in ring:
                    try:
                        hring.append([round(pt.x() - cx, 3), round(pt.y() - cy, 3)])
                    except Exception:
                        continue
                if len(hring) >= 2 and hring[0] == hring[-1]:
                    hring = hring[:-1]
                if len(hring) >= 3:
                    holes.append(hring)

            part_obj = {"outer": outer, "holes": holes}
            if outer_ll:
                part_obj["outer_ll"] = outer_ll
            parts.append(part_obj)

        if not parts:
            return None

        # Compute geometric centroid for minimap anchoring
        ll_center = None
        try:
            c = geom.centroid().asPoint()
            if local_to_lonlat:
                ll_center = local_to_lonlat(c.x() - cx, c.y() - cy)
        except Exception:
            pass

        return {
            "parts": parts,
            "h": round(float(height), 2),
            "base": round(float(base), 2),
            "ll_center": ll_center,
            "composite": score["composite"],
            "comfort": score["comfort"],
            "solar": score["solar"],
            "skyview": score["skyview"],
            "greenview": score["greenview"],
            "shading": score["shading"],
            "landmark": score["landmark"],
            "svf_val": score.get("svf_val", 0),
            "gvi_val": score.get("gvi_val", 0),
            "ghi_val": score.get("ghi_val", 0),
            "shadow_val": score.get("shadow_val", 0),
            "shadow_m": score.get("shadow_m", 0),
        }

    def _voxelize_vegetation(self, vegetation, vsz, cx, cy, dem, tcrs, boundary_geom=None):
        voxels = []
        for item in vegetation:
            g = item["geom"]
            bb = g.boundingBox()
            x0 = math.floor(bb.xMinimum() / vsz) * vsz
            x1 = math.ceil(bb.xMaximum() / vsz) * vsz
            y0 = math.floor(bb.yMinimum() / vsz) * vsz
            y1 = math.ceil(bb.yMaximum() / vsz) * vsz
            created = 0
            x = x0
            while x <= x1:
                y = y0
                while y <= y1:
                    px = x + vsz / 2.0
                    py = y + vsz / 2.0
                    if g.contains(QgsGeometry.fromPointXY(QgsPointXY(px, py))):
                        # Extra safety: also filter by outer study boundary
                        if boundary_geom and not self._point_in_boundary(px, py, boundary_geom):
                            y += vsz
                            continue
                        base = self.sampleDEM(dem, tcrs, px, py)
                        voxels.append({
                            "x": px - cx,
                            "y": py - cy,
                            "z": base,
                            "type": "vegetation",
                            "composite": 0.25,
                            "comfort": 0.75,
                            "solar": 0.15,
                            "skyview": 0.55,
                            "greenview": 0.95,
                            "shading": 0.80,
                            "landmark": 0.0,
                        })
                        created += 1
                    y += vsz
                x += vsz
            if created == 0:
                try:
                    c = g.centroid().asPoint()
                    cpx, cpy = c.x(), c.y()
                except Exception:
                    continue
                # Skip centroid fallback if outside boundary (avoid out-of-boundary artifacts)
                if boundary_geom and not self._point_in_boundary(cpx, cpy, boundary_geom):
                    continue
                base = self.sampleDEM(dem, tcrs, cpx, cpy)
                voxels.append({
                    "x": cpx - cx,
                    "y": cpy - cy,
                    "z": base,
                    "type": "vegetation",
                    "composite": 0.25,
                    "comfort": 0.75,
                    "solar": 0.15,
                    "skyview": 0.55,
                    "greenview": 0.95,
                    "shading": 0.80,
                    "landmark": 0.0,
                })
        return voxels

    def _voxelize_canopy(self, canopy_samples, vsz):
        voxels = []
        for s in canopy_samples:
            zlevels = max(1, int(math.ceil(s["h"] / vsz)))
            for zi in range(zlevels):
                voxels.append({
                    "x": s["lx"],
                    "y": s["ly"],
                    "z": zi * vsz,
                    "type": "canopy",
                    "composite": 0.30,
                    "comfort": 0.80,
                    "solar": 0.10,
                    "skyview": 0.45,
                    "greenview": 1.0,
                    "shading": 0.85,
                    "landmark": 0.0,
                })
        return voxels

    # ------------------------------------------------------------------
    # QGIS output layers
    # ------------------------------------------------------------------

    def addAnalysisLayer(self, analysis, tcrs, cx, cy):
        layer = QgsVectorLayer("Point?crs={}".format(tcrs.authid()), "voxcity_analysis_points", "memory")
        prov = layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("composite", QVariant.Double))
        fields.append(QgsField("comfort", QVariant.Double))
        fields.append(QgsField("solar", QVariant.Double))
        fields.append(QgsField("skyview", QVariant.Double))
        fields.append(QgsField("greenview", QVariant.Double))
        fields.append(QgsField("shading", QVariant.Double))
        fields.append(QgsField("landmark", QVariant.Double))
        fields.append(QgsField("svf_val", QVariant.Double))      # Sky View Factor (Oke 1987)
        fields.append(QgsField("gvi_pct", QVariant.Double))      # Green View Index % (Yang 2009)
        fields.append(QgsField("ghi_wm2", QVariant.Double))      # Global Horizontal Irradiance W/m2 (ASHRAE)
        fields.append(QgsField("shadow_frc", QVariant.Double))   # Shadow coverage fraction (Ratti 2004)
        fields.append(QgsField("shadow_m", QVariant.Double))     # Mean shadow length meters
        fields.append(QgsField("ground_z", QVariant.Double))
        prov.addAttributes(fields)
        layer.updateFields()
        feats = []
        for a in analysis:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(a["x"] + cx, a["y"] + cy)))
            feat.setAttributes([
                a["composite"], a["comfort"], a["solar"], a["skyview"],
                a["greenview"], a["shading"], a["landmark"],
                a.get("svf_val", 0), a.get("gvi_val", 0), a.get("ghi_val", 0),
                a.get("shadow_val", 0), a.get("shadow_m", 0),
                a["z"]
            ])
            feats.append(feat)
        prov.addFeatures(feats)
        symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": "#2563eb", "size": "1.8", "outline_color": "#ffffff", "outline_width": "0.2"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        QgsProject.instance().addMapLayer(layer)

    def addCentroidLayer(self, centroids, tcrs, cx, cy):
        layer = QgsVectorLayer("Point?crs={}".format(tcrs.authid()), "voxcity_building_centroids", "memory")
        prov = layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("height", QVariant.Double))
        fields.append(QgsField("composite", QVariant.Double))
        fields.append(QgsField("comfort", QVariant.Double))
        fields.append(QgsField("solar", QVariant.Double))
        fields.append(QgsField("skyview", QVariant.Double))
        fields.append(QgsField("greenview", QVariant.Double))
        fields.append(QgsField("shading", QVariant.Double))
        fields.append(QgsField("landmark", QVariant.Double))
        fields.append(QgsField("svf_val", QVariant.Double))      # Sky View Factor (Oke 1987)
        fields.append(QgsField("gvi_pct", QVariant.Double))      # Green View Index % (Yang 2009)
        fields.append(QgsField("ghi_wm2", QVariant.Double))      # Global Horizontal Irradiance W/m2 (ASHRAE)
        fields.append(QgsField("shadow_frc", QVariant.Double))   # Shadow coverage fraction (Ratti 2004)
        fields.append(QgsField("shadow_m", QVariant.Double))     # Mean shadow length meters
        fields.append(QgsField("ground_z", QVariant.Double))
        prov.addAttributes(fields)
        layer.updateFields()
        feats = []
        for c in centroids:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(c["x"] + cx, c["y"] + cy)))
            feat.setAttributes([
                c["height"], c["composite"], c["comfort"], c["solar"],
                c["skyview"], c["greenview"], c["shading"], c["landmark"],
                c.get("svf_val", 0), c.get("gvi_val", 0), c.get("ghi_val", 0),
                c.get("shadow_val", 0), c.get("shadow_m", 0),
                c["z"]
            ])
            feats.append(feat)
        prov.addFeatures(feats)
        symbol = QgsMarkerSymbol.createSimple({"name": "square", "color": "#22c55e", "size": "1.7", "outline_color": "#0f172a", "outline_width": "0.2"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        QgsProject.instance().addMapLayer(layer)

    def buildHTML(self, title, voxels, solids, roads, analysis, terrain, terrain_step, building_mode, geo_ref, canopy_samples=None):
        vox_json = json.dumps(voxels, ensure_ascii=False)
        sol_json = json.dumps(solids, ensure_ascii=False)
        roads_json = json.dumps(roads, ensure_ascii=False)
        ana_json = json.dumps(analysis, ensure_ascii=False)
        ter_json = json.dumps(terrain, ensure_ascii=False)
        geo_json = json.dumps(geo_ref, ensure_ascii=False)
        # Canopy samples for tree rendering - independent of voxel generation.
        # Each sample = 1 tree. Exported separately so trees render even when
        # canopy_mode = "analysis only" (no canopy voxels in main VOXELS array).
        trees_data = []
        if canopy_samples:
            for s in canopy_samples:
                trees_data.append({
                    "x": s.get("lx", 0),
                    "y": s.get("ly", 0),
                    "h": max(1.0, s.get("h", 5.0))
                })
        trees_json = json.dumps(trees_data, ensure_ascii=False)
        bmode_str = "solid" if building_mode == 0 else "voxel"

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}
html, body {{
  width: 100%;
  height: 100%;
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-feature-settings: 'cv11', 'ss01', 'ss03';
  background: #060d1a;
  color: #e5eefc;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  letter-spacing: -0.005em;
}}
.mono {{
  font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Consolas, monospace;
}}
#app {{
  position: fixed;
  inset: 0;
}}
#panel {{
  position: absolute;
  top: 16px;
  left: 16px;
  width: 400px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  background: rgba(7,18,34,0.88);
  border: 1px solid rgba(255,255,255,0.09);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 18px;
  padding: 17px 18px;
  z-index: 10;
  box-shadow: 0 14px 40px rgba(0,0,0,0.35);
}}
#panel::-webkit-scrollbar {{
  width: 8px;
}}
#panel::-webkit-scrollbar-thumb {{
  background: rgba(148,163,184,0.35);
  border-radius: 99px;
}}
#title {{
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 4px;
  background: linear-gradient(135deg, #e0f2fe 0%, #93c5fd 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
#subtitle {{
  font-size: 12px;
  font-weight: 500;
  color: #9bb0cf;
  margin-bottom: 4px;
  line-height: 1.45;
  letter-spacing: -0.005em;
}}
#subnote {{
  font-size: 10px;
  font-weight: 500;
  color: #7f93b2;
  margin-bottom: 14px;
  line-height: 1.45;
  letter-spacing: 0.01em;
}}
.grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 14px;
}}
.grid-3 {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-bottom: 14px;
}}
.card {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 12px;
  padding: 10px 11px;
  transition: background 0.2s ease, border-color 0.2s ease;
}}
.card:hover {{
  background: rgba(255,255,255,0.055);
  border-color: rgba(96,165,250,0.25);
}}
.card .v {{
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 17px;
  font-weight: 600;
  color: #cbe1ff;
  letter-spacing: -0.02em;
}}
.card .l {{
  font-size: 10.5px;
  font-weight: 500;
  color: #8ea6c7;
  margin-top: 3px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}}
.section {{
  margin-top: 14px;
}}
.section-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: #86a3cc;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
select, button {{
  width: 100%;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.09);
  background: rgba(255,255,255,0.05);
  color: #e5eefc;
  padding: 10px 12px;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.005em;
}}
select {{
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  background-image:
    linear-gradient(45deg, transparent 50%, #cbd5e1 50%),
    linear-gradient(135deg, #cbd5e1 50%, transparent 50%);
  background-position:
    calc(100% - 18px) calc(50% - 3px),
    calc(100% - 12px) calc(50% - 3px);
  background-size: 6px 6px, 6px 6px;
  background-repeat: no-repeat;
  padding-right: 32px;
}}
select:focus {{
  outline: none;
  border-color: rgba(96,165,250,0.7);
  box-shadow: 0 0 0 3px rgba(96,165,250,0.14);
}}
select option {{
  background: #0b1730;
  color: #e5eefc;
}}
button {{
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.08s ease;
}}
button:hover {{
  background: rgba(96,165,250,0.14);
  border-color: rgba(96,165,250,0.28);
}}
button:active {{
  transform: scale(0.98);
}}
.row {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-top: 8px;
}}
.legend {{
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 10;
  background: rgba(7,18,34,0.85);
  border: 1px solid rgba(255,255,255,0.09);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 16px;
  padding: 13px 15px;
  min-width: 260px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.3);
}}
.legend-title {{
  font-size: 12px;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin-bottom: 8px;
}}
.bar {{
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(90deg, #1d4ed8 0%, #16a34a 33%, #ca8a04 66%, #dc2626 100%);
  margin-bottom: 6px;
}}
.bar-labels {{
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-weight: 500;
  color: #9bb0cf;
  letter-spacing: 0.02em;
}}
.small {{
  margin-top: 10px;
  font-size: 10.5px;
  font-weight: 400;
  color: #9bb0cf;
  line-height: 1.6;
  letter-spacing: -0.002em;
}}
.badge-row {{
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 8px;
}}
.badge {{
  font-size: 10.5px;
  font-weight: 500;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.055);
  border: 1px solid rgba(255,255,255,0.09);
  color: #cbd5e1;
  letter-spacing: -0.003em;
}}
#loading {{
  position: fixed;
  inset: 0;
  background: rgba(4,10,20,0.96);
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 14px;
}}
.spinner {{
  width: 42px;
  height: 42px;
  border: 3px solid rgba(255,255,255,0.12);
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}}
@keyframes spin {{
  to {{ transform: rotate(360deg); }}
}}
#loadingText {{
  font-size: 13px;
  color: #b7c9e6;
}}
.toggle-on {{
  outline: 1px solid rgba(96,165,250,0.7);
  background: rgba(96,165,250,0.18);
}}
.status-ok {{
  color: #86efac;
}}
.status-warn {{
  color: #fcd34d;
}}

/* Minimap container */
#minimap-wrap {{
  position: absolute;
  top: 16px;
  right: 16px;
  width: 340px;
  height: 260px;
  z-index: 10;
  background: rgba(7,18,34,0.88);
  border: 1px solid rgba(255,255,255,0.09);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 18px;
  padding: 10px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.35);
  display: flex;
  flex-direction: column;
}}
#minimap-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 4px 8px 4px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 8px;
}}
#minimap-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: #86a3cc;
  text-transform: uppercase;
}}
#minimap-coords {{
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9.5px;
  color: #93c5fd;
  letter-spacing: -0.01em;
}}
#minimap {{
  flex: 1 1 auto;
  min-height: 180px;
  border-radius: 12px;
  overflow: hidden;
  background: #0b1730;
  position: relative;
}}
#minimap.disabled {{
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7f93b2;
  font-size: 11px;
  font-weight: 500;
}}

/* Custom minimap toolbar */
#minimap-toolbar {{
  display: flex;
  gap: 5px;
  margin-top: 8px;
}}
#minimap-toolbar button {{
  flex: 1;
  font-size: 10.5px;
  font-weight: 600;
  padding: 7px 6px;
  letter-spacing: 0.02em;
  border-radius: 8px;
}}
#minimap-toolbar button.active {{
  background: rgba(96,165,250,0.22);
  border-color: rgba(96,165,250,0.55);
  color: #dbeafe;
}}

/* Analytics panel (below minimap, above legend) */
#analytics-wrap {{
  position: absolute;
  top: 288px;
  right: 16px;
  width: 340px;
  z-index: 10;
  background: rgba(7,18,34,0.88);
  border: 1px solid rgba(255,255,255,0.09);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: 18px;
  padding: 10px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.35);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 320px - 110px);
  overflow: hidden;
}}
#analytics-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 4px 8px 4px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 8px;
}}
#analytics-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #93c5fd;
}}
#btnAnalyticsToggle {{
  padding: 4px 10px;
  font-size: 10px;
  background: rgba(96,165,250,0.12);
  border: 1px solid rgba(96,165,250,0.25);
  color: #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  letter-spacing: 0.04em;
}}
#btnAnalyticsToggle:hover {{
  background: rgba(96,165,250,0.22);
}}
#btnAnalyticsToggle.active {{
  background: rgba(96,165,250,0.22);
  border-color: rgba(96,165,250,0.55);
  color: #dbeafe;
}}
#analytics-body {{
  overflow-y: auto;
  max-height: 460px;
}}
#analytics-body.hidden {{
  display: none;
}}
.analytics-section-label {{
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #86a3cc;
  margin: 6px 2px 4px 2px;
}}
#analyticsBars, #analyticsRadar {{
  display: block;
  width: 100%;
  height: auto;
}}
/* Export button prominent */
#btnExport {{
  background: linear-gradient(135deg, rgba(59,130,246,0.28) 0%, rgba(139,92,246,0.28) 100%);
  border-color: rgba(139,92,246,0.45);
  color: #e0e7ff;
  font-weight: 600;
  letter-spacing: 0.01em;
  margin-top: 10px;
}}
#btnExport:hover {{
  background: linear-gradient(135deg, rgba(59,130,246,0.38) 0%, rgba(139,92,246,0.38) 100%);
  border-color: rgba(139,92,246,0.7);
}}
#exportStatus {{
  margin-top: 6px;
  font-size: 10.5px;
  color: #93c5fd;
  text-align: center;
  min-height: 14px;
}}
.param-block {{
  background: rgba(255,255,255,0.035);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 10px;
  margin-top: 8px;
}}
.slider-wrap {{
  margin-top: 10px;
}}
.slider-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}}
.slider-label {{
  font-size: 11px;
  color: #cbd5e1;
}}
.slider-value {{
  font-size: 11px;
  color: #93c5fd;
  font-weight: 700;
}}
input[type="range"] {{
  width: 100%;
  accent-color: #60a5fa;
}}
#analysisDescription {{
  background: rgba(255,255,255,0.035);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 12px;
  font-size: 11px;
  line-height: 1.6;
  color: #cbd5e1;
}}
#analysisDescription b {{
  color: #e5eefc;
}}
</style>
</head>
<body>
<div id="app"></div>

<div id="loading">
  <div class="spinner"></div>
  <div id="loadingText">Initializing Vox City Viewer...</div>
</div>

<div id="panel">
  <div id="title">{title}</div>
  <div id="subtitle">Reading Cities Through Form, Terrain, and Intelligence</div>
  <div id="subnote">UA ITB - Sagamartha | Developed by Firman Afrianto and Maya Safira</div>

  <div class="grid">
    <div class="card"><div class="v" id="voxelCount">0</div><div class="l">Total Voxels</div></div>
    <div class="card"><div class="v" id="analysisCount">0</div><div class="l">Analysis Points</div></div>
    <div class="card"><div class="v" id="avgScore">0</div><div class="l">Average</div></div>
    <div class="card"><div class="v" id="maxScore">0</div><div class="l">Max</div></div>
  </div>

  <div class="grid">
    <div class="card"><div class="v" id="minScore">0</div><div class="l">Min</div></div>
    <div class="card"><div class="v" id="hotspotPct">0%</div><div class="l">Hotspot %</div></div>
    <div class="card"><div class="v" id="terrainMin">0</div><div class="l">Terrain Min</div></div>
    <div class="card"><div class="v" id="terrainMax">0</div><div class="l">Terrain Max</div></div>
  </div>

  <div class="grid-3">
    <div class="card"><div class="v" id="buildingCount">0</div><div class="l">Building</div></div>
    <div class="card"><div class="v" id="vegetationCount">0</div><div class="l">Vegetation</div></div>
    <div class="card"><div class="v" id="canopyCount">0</div><div class="l">Canopy</div></div>
  </div>

  <div class="section">
    <div class="section-title">Analysis Mode</div>
    <select id="modeSelect">
      <option value="composite">Composite</option>
      <option value="comfort">Comfort</option>
      <option value="solar">Solar</option>
      <option value="skyview">Sky View</option>
      <option value="greenview">Green View</option>
      <option value="shading">Shading</option>
      <option value="landmark">Landmark</option>
    </select>
    <div class="row" style="grid-template-columns: 1fr 1fr; margin-top: 8px;">
      <button id="btnUnitScore" class="toggle-on">Score 0-1</button>
      <button id="btnUnitPhysical">Physical Unit</button>
    </div>
    <div id="physicalReadout" class="mono" style="margin-top:8px;font-size:11px;color:#93c5fd;text-align:center;min-height:14px;"></div>
  </div>

  <div class="section">
    <div class="section-title">Interactive Parameters</div>
    <div class="param-block">
      <div class="slider-wrap">
        <div class="slider-head">
          <div class="slider-label">View Radius</div>
          <div class="slider-value" id="radiusValue">250 m</div>
        </div>
        <input id="radiusSlider" type="range" min="50" max="600" step="10" value="250">
      </div>

      <div class="slider-wrap">
        <div class="slider-head">
          <div class="slider-label">Sun Azimuth</div>
          <div class="slider-value" id="azimuthValue">135°</div>
        </div>
        <input id="azimuthSlider" type="range" min="0" max="360" step="1" value="135">
      </div>

      <div class="slider-wrap">
        <div class="slider-head">
          <div class="slider-label">Sun Elevation</div>
          <div class="slider-value" id="elevationValue">45°</div>
        </div>
        <input id="elevationSlider" type="range" min="1" max="89" step="1" value="45">
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">What This Analysis Means</div>
    <div id="analysisDescription"></div>
  </div>

  <div class="section">
    <div class="section-title">Layer Controls</div>
    <div class="row">
      <button id="btnTerrain" class="toggle-on">Terrain</button>
      <button id="btnVoxels" class="toggle-on">Voxels</button>
      <button id="btnAnalysis" class="toggle-on">Analysis</button>
    </div>
    <div class="row">
      <button id="btnRoads" class="toggle-on">Roads</button>
      <button id="btnReset">Reset Cam</button>
      <button id="btnRotate">Auto Rotate</button>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Status</div>
    <div class="badge-row">
      <div class="badge" id="statusTerrain">Terrain: -</div>
      <div class="badge" id="statusMode">Mode: Composite</div>
      <div class="badge" id="statusMap">Map: -</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Export</div>
    <button id="btnExport">Export PNG (3D + Map + Legend)</button>
    <div id="exportStatus"></div>
  </div>

  <div class="section">
    <div class="small">
      Terrain is rendered as a smooth mesh. Buildings, vegetation, and canopy are visualised according to the render mode.
      The context map in the top right is synchronised with the 3D camera. The Export button produces a PNG containing
      the 3D view, 2D map, and legend for reports or publications.
    </div>
  </div>
</div>

<div id="minimap-wrap">
  <div id="minimap-header">
    <div id="minimap-title">Context Map</div>
    <div id="minimap-coords" class="mono">—</div>
  </div>
  <div id="minimap"></div>
  <div id="minimap-toolbar">
    <button id="btnMapReset" title="Reset to initial extent">Reset</button>
    <button id="btnMapFit" title="Zoom to data extent">Extent</button>
    <button id="btnMapZoomIn" title="Zoom in">+</button>
    <button id="btnMapZoomOut" title="Zoom out">−</button>
    <button id="btnMapPan" title="Toggle pan sync to 3D" class="active">Sync</button>
    <button id="btnMapHeatmap" title="Toggle analysis heatmap overlay" class="active">Heat</button>
  </div>
</div>

<div id="analytics-wrap">
  <div id="analytics-header">
    <div id="analytics-title">Indicator Analytics</div>
    <button id="btnAnalyticsToggle" title="Show / hide indicator charts" class="active">Hide</button>
  </div>
  <div id="analytics-body">
    <div class="analytics-section-label">BAR — indicator averages (all modes)</div>
    <canvas id="analyticsBars" width="640" height="200"></canvas>
    <div class="analytics-section-label">RADAR — profile (solar inverted so higher = better)</div>
    <canvas id="analyticsRadar" width="640" height="300"></canvas>
  </div>
</div>

<div class="legend">
  <div class="legend-title" id="legendTitle">Composite</div>
  <div class="bar"></div>
  <div class="bar-labels">
    <span>Low</span>
    <span>Medium</span>
    <span>High</span>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>

<script>
// Global error handler - if something crashes before buildScene finishes,
// at least hide the loading overlay and show the error to the user.
window.addEventListener("error", (ev) => {{
  console.error("[VoxCity] Uncaught error:", ev.error || ev.message);
  const loading = document.getElementById("loading");
  if (loading && loading.style.display !== "none") {{
    const txt = document.getElementById("loadingText");
    if (txt) {{
      txt.innerHTML = "Viewer error: " + (ev.message || "unknown") +
        "<br><span style='font-size:10px;opacity:0.7'>Open DevTools (F12) → Console for details</span>";
      txt.style.color = "#fca5a5";
    }}
    // Hide spinner but keep message visible
    const sp = document.querySelector(".spinner");
    if (sp) sp.style.display = "none";
  }}
}});

const VOXELS = {vox_json};
const SOLIDS = {sol_json};
const ROADS = {roads_json};
const ANALYSIS = {ana_json};
const TERRAIN = {ter_json};
const TREES_DATA = {trees_json};  // canopy samples - independent tree data for rendering
const GEO_REF = {geo_json};
const TERRAIN_STEP = {terrain_step};
const BUILDING_MODE = "{bmode_str}";

let scene, camera, renderer, controls;
let terrainMesh = null;
let voxelGroup = null;
let voxelMeshes = {{}};
let voxelIndexMap = {{}};
let solidGroup = null;
let solidMeshes = [];
let analysisGroup = null;
let analysisMesh = null;
let roadsGroup = null;
let treesGroup = null;
let treesTrunkMesh = null;
let treesCrownMesh = null;
let autoRotate = false;
let currentMode = "composite";
let displayMode = "score";  // "score" (0-1) or "physical" (SVF/GVI/W-m²/m)

// Indicator direction & labels for bar/radar charts
// direction: "good" (higher = better) | "bad" (higher = worse) | "neutral"
// Declared HERE (top of script) to avoid TDZ errors - renderAnalyticsPanel()
// in init() references these before the PNG export block is reached in
// linear script execution.
const INDICATOR_DIRECTIONS = [
  {{ key: "composite", label: "Composite", direction: "good" }},
  {{ key: "comfort",   label: "Comfort",   direction: "good" }},
  {{ key: "greenview", label: "Green View", direction: "good" }},
  {{ key: "shading",   label: "Shading",   direction: "good" }},
  {{ key: "skyview",   label: "Sky View",  direction: "neutral" }},
  {{ key: "landmark",  label: "Landmark",  direction: "good" }},
  {{ key: "solar",     label: "Solar",     direction: "bad" }}
];

function computeIndicatorAverages() {{
  const out = {{}};
  for (const ind of INDICATOR_DIRECTIONS) {{
    const vs = ANALYSIS.map(a => a[ind.key] || 0).filter(v => isFinite(v));
    if (vs.length) {{
      let sum = 0;
      for (const v of vs) sum += v;
      out[ind.key] = sum / vs.length;
    }} else {{
      out[ind.key] = 0;
    }}
  }}
  return out;
}}

// Minimap state - MUST be declared before init()/buildScene() is called
let minimapCanvas = null;
let minimapCtx = null;
let minimapViewport = {{ scale: 1, offsetX: 0, offsetY: 0 }};
let minimapInitialViewport = null;
let syncPanEnabled = true;
let heatmapEnabled = true;
let minimapDragging = false;
let minimapDragStart = null;
let _cachedExtX = null, _cachedExtY = null;

let viewRadius = 250;
let sunAzimuth = 135;
let sunElevation = 45;

// Maps analysis mode to its physical-unit field & formatting
// Citations: SVF Oke 1987; GVI Yang 2009; GHI ASHRAE/Iqbal; Shadow Ratti & Richens 2004
const physicalMeta = {{
  skyview:   {{ field: "svf_val",    unit: "SVF",    fmt: (v) => v.toFixed(2),         ref: "Oke 1987" }},
  greenview: {{ field: "gvi_val",    unit: "%",      fmt: (v) => v.toFixed(1) + "%",   ref: "Yang 2009" }},
  solar:     {{ field: "ghi_val",    unit: "W/m²",   fmt: (v) => v.toFixed(0) + " W/m²", ref: "ASHRAE" }},
  shading:   {{ field: "shadow_val", unit: "frac",   fmt: (v) => v.toFixed(2),         ref: "Ratti 2004" }},
  composite: {{ field: null, unit: "score", fmt: (v) => v.toFixed(2), ref: "weighted" }},
  comfort:   {{ field: null, unit: "score", fmt: (v) => v.toFixed(2), ref: "weighted" }},
  landmark:  {{ field: null, unit: "score", fmt: (v) => v.toFixed(2), ref: "proxy" }}
}};

function getPhysicalValue(obj, mode) {{
  const meta = physicalMeta[mode];
  if (!meta || !meta.field) return null;
  const v = obj[meta.field];
  return (v === undefined || v === null) ? null : v;
}}

function formatPhysical(v, mode) {{
  const meta = physicalMeta[mode];
  if (!meta || v === null) return "—";
  return meta.fmt(v);
}}

const analysisMeta = {{
  composite: {{
    title: "Composite",
    built_from: "weighted combination of solar, sky view, green view, landmark, and shading",
    purpose: "serves as an integrative score of spatial quality for reading overall performance"
  }},
  comfort: {{
    title: "Comfort",
    built_from: "green view, shading, sky view, and reduced solar exposure",
    purpose: "indicates potential microclimatic and visual comfort"
  }},
  solar: {{
    title: "Solar",
    built_from: "sun exposure, sky openness, and shadow effects",
    purpose: "highlights areas more exposed to solar radiation"
  }},
  skyview: {{
    title: "Sky View",
    built_from: "building and canopy obstruction relative to sky openness",
    purpose: "measures how open a location is toward the sky"
  }},
  greenview: {{
    title: "Green View",
    built_from: "surrounding vegetation polygons and canopy raster",
    purpose: "shows the dominance of green elements shaping spatial perception"
  }},
  shading: {{
    title: "Shading",
    built_from: "building blocking and vegetation / canopy shading",
    purpose: "identifies areas that are more shaded and thermally moderated"
  }},
  landmark: {{
    title: "Landmark",
    built_from: "distance to landmarks and visibility openness",
    purpose: "reflects visual orientation strength and spatial legibility"
  }}
}};

init();
buildScene();
animate();

function init() {{
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x06111f);

  camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 100000);
  camera.position.set(500, 400, 500);

  renderer = new THREE.WebGLRenderer({{ antialias: true, preserveDrawingBuffer: true }});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.getElementById("app").appendChild(renderer.domElement);

  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  const hemi = new THREE.HemisphereLight(0xdbeafe, 0x0b1220, 1.35);
  scene.add(hemi);

  const dir = new THREE.DirectionalLight(0xffffff, 1.15);
  dir.position.set(300, 500, 250);
  scene.add(dir);

  // Grid added later in buildScene() after terrain is known, so it can sit at terrain base

  window.addEventListener("resize", onResize);

  document.getElementById("btnTerrain").addEventListener("click", () => toggleLayer("terrain"));
  document.getElementById("btnVoxels").addEventListener("click", () => toggleLayer("voxels"));
  document.getElementById("btnAnalysis").addEventListener("click", () => toggleLayer("analysis"));
  document.getElementById("btnRoads").addEventListener("click", () => toggleLayer("roads"));
  document.getElementById("btnReset").addEventListener("click", resetCamera);
  document.getElementById("btnRotate").addEventListener("click", () => {{
    autoRotate = !autoRotate;
    document.getElementById("btnRotate").classList.toggle("toggle-on", autoRotate);
  }});

  document.getElementById("modeSelect").addEventListener("change", (e) => {{
    currentMode = e.target.value;
    const label = e.target.options[e.target.selectedIndex].text;
    document.getElementById("statusMode").innerText = "Mode: " + label;
    updateAnalysisDescription();
    recolorVoxels();
    recolorSolids();
    recolorAnalysis();
    drawMinimapBuildings();
    updateDashboard();
    updateLegendLabel();
  }});

  document.getElementById("radiusSlider").addEventListener("input", (e) => {{
    viewRadius = parseFloat(e.target.value);
    document.getElementById("radiusValue").innerText = viewRadius.toFixed(0) + " m";
    recolorVoxels();
    recolorSolids();
    recolorAnalysis();
    drawMinimapBuildings();
    updateDashboard();
  }});

  document.getElementById("azimuthSlider").addEventListener("input", (e) => {{
    sunAzimuth = parseFloat(e.target.value);
    document.getElementById("azimuthValue").innerText = sunAzimuth.toFixed(0) + "°";
    recolorVoxels();
    recolorSolids();
    recolorAnalysis();
    drawMinimapBuildings();
    updateDashboard();
  }});

  document.getElementById("elevationSlider").addEventListener("input", (e) => {{
    sunElevation = parseFloat(e.target.value);
    document.getElementById("elevationValue").innerText = sunElevation.toFixed(0) + "°";
    recolorVoxels();
    recolorSolids();
    recolorAnalysis();
    drawMinimapBuildings();
    updateDashboard();
  }});

  updateAnalysisDescription();
  updateLegendLabel();

  // Relabel toggle button based on render mode
  if (BUILDING_MODE === "solid") {{
    document.getElementById("btnVoxels").innerText = "Buildings";
  }}

  // Minimap toolbar
  document.getElementById("btnMapReset").addEventListener("click", minimapReset);
  document.getElementById("btnMapFit").addEventListener("click", minimapFitExtent);
  document.getElementById("btnMapZoomIn").addEventListener("click", () => {{
    if (!minimapCanvas) return;
    const r = minimapCanvas.getBoundingClientRect();
    zoomMinimapAt(r.width / 2, r.height / 2, 1.3);
  }});
  document.getElementById("btnMapZoomOut").addEventListener("click", () => {{
    if (!minimapCanvas) return;
    const r = minimapCanvas.getBoundingClientRect();
    zoomMinimapAt(r.width / 2, r.height / 2, 1 / 1.3);
  }});
  document.getElementById("btnMapPan").addEventListener("click", () => {{
    syncPanEnabled = !syncPanEnabled;
    document.getElementById("btnMapPan").classList.toggle("active", syncPanEnabled);
    if (syncPanEnabled) drawMinimap();
  }});

  document.getElementById("btnMapHeatmap").addEventListener("click", () => {{
    heatmapEnabled = !heatmapEnabled;
    document.getElementById("btnMapHeatmap").classList.toggle("active", heatmapEnabled);
    drawMinimap();
  }});

  // Score ↔ Physical Unit toggle
  document.getElementById("btnUnitScore").addEventListener("click", () => {{
    displayMode = "score";
    document.getElementById("btnUnitScore").classList.add("toggle-on");
    document.getElementById("btnUnitPhysical").classList.remove("toggle-on");
    updateDashboard();
    updateLegendLabel();
  }});
  document.getElementById("btnUnitPhysical").addEventListener("click", () => {{
    displayMode = "physical";
    document.getElementById("btnUnitPhysical").classList.add("toggle-on");
    document.getElementById("btnUnitScore").classList.remove("toggle-on");
    updateDashboard();
    updateLegendLabel();
  }});

  // Analytics panel toggle
  document.getElementById("btnAnalyticsToggle").addEventListener("click", () => {{
    const body = document.getElementById("analytics-body");
    const btn = document.getElementById("btnAnalyticsToggle");
    const isHidden = body.classList.toggle("hidden");
    btn.innerText = isHidden ? "Show" : "Hide";
    btn.classList.toggle("active", !isHidden);
  }});
  // Initial render of bar+radar to the runtime canvases
  renderAnalyticsPanel();

  // Export PNG
  document.getElementById("btnExport").addEventListener("click", exportPNG);
}}

// Render the indicator bar + radar panels to their runtime canvases.
// Canvases are sized using devicePixelRatio for crisp text on hi-DPI displays.
// Reuses the same drawIndicatorBars / drawIndicatorRadar functions that also
// power the PNG export, so the two visualizations stay identical.
function renderAnalyticsPanel() {{
  const barCanvas = document.getElementById("analyticsBars");
  const radarCanvas = document.getElementById("analyticsRadar");
  if (!barCanvas || !radarCanvas) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);

  // --- Bar canvas ---
  const barCssW = barCanvas.clientWidth || 320;
  const barRows = INDICATOR_DIRECTIONS.length;
  const barCssH = 24 + (barRows * 22) + 30;  // header + rows + footnote
  barCanvas.width = Math.floor(barCssW * dpr);
  barCanvas.height = Math.floor(barCssH * dpr);
  barCanvas.style.height = barCssH + "px";
  const bctx = barCanvas.getContext("2d");
  bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  bctx.clearRect(0, 0, barCssW, barCssH);
  drawIndicatorBars(bctx, 6, 6, barCssW - 12, barCssH - 12);

  // --- Radar canvas ---
  const radCssW = radarCanvas.clientWidth || 320;
  const radCssH = 260;  // enough for top+bottom label breathing room
  radarCanvas.width = Math.floor(radCssW * dpr);
  radarCanvas.height = Math.floor(radCssH * dpr);
  radarCanvas.style.height = radCssH + "px";
  const rctx = radarCanvas.getContext("2d");
  rctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  rctx.clearRect(0, 0, radCssW, radCssH);
  drawIndicatorRadar(rctx, 6, 6, radCssW - 12, radCssH - 12);
}}

function buildScene() {{
  const T0 = performance.now();
  const timings = {{}};
  const setLoading = (msg) => {{
    const el = document.getElementById("loadingText");
    if (el) el.innerText = msg;
  }};

  const step = (name, fn) => {{
    setLoading(name + "...");
    const t = performance.now();
    try {{ fn(); }}
    catch (e) {{ console.error(name + " failed:", e); }}
    timings[name] = Math.round(performance.now() - t);
    console.log("[VoxCity]", name, "took", timings[name], "ms");
  }};

  step("Terrain", buildTerrain);
  step("Grid", buildGrid);

  step("Buildings", () => {{
    if (BUILDING_MODE === "solid") {{
      buildSolids();
      buildVegetationAndCanopyVoxels();
    }} else {{
      buildVoxels();
    }}
  }});

  step("Analysis", buildAnalysis);
  step("Roads", buildRoads);
  step("Trees", buildTrees);
  step("Minimap", buildMinimap);
  step("Dashboard", updateDashboard);
  step("ResetCam", resetCamera);

  try {{
    document.getElementById("statusTerrain").innerHTML = `Terrain: <span class="status-ok">${{terrainMesh ? "OK" : "Missing"}}</span>`;
  }} catch (e) {{ console.error("status update failed:", e); }}

  const total = Math.round(performance.now() - T0);
  console.log("[VoxCity] TOTAL buildScene:", total, "ms", timings);

  // ALWAYS hide loading, even if something above failed
  document.getElementById("loading").style.display = "none";
}}

function buildGrid() {{
  let baseY = 0;
  if (TERRAIN && TERRAIN.length && TERRAIN[0] && TERRAIN[0].length) {{
    let mn = Infinity;
    for (let i = 0; i < TERRAIN.length; i++) {{
      for (let j = 0; j < TERRAIN[i].length; j++) {{
        const v = TERRAIN[i][j];
        if (v !== null && v !== undefined && !isNaN(v) && v < mn) mn = v;
      }}
    }}
    if (mn !== Infinity) baseY = mn - 2;
  }}
  const grid = new THREE.GridHelper(5000, 80, 0x22324a, 0x152235);
  grid.position.y = baseY;
  scene.add(grid);
}}

function updateLegendLabel() {{
  const sel = document.getElementById("modeSelect");
  const modeText = sel ? sel.options[sel.selectedIndex].text : currentMode;
  const meta = physicalMeta[currentMode];
  const titleEl = document.getElementById("legendTitle");
  if (!titleEl) return;

  if (displayMode === "physical" && meta && meta.field) {{
    titleEl.innerText = modeText + " (" + meta.unit + ")";
    // Update bar labels to show physical range
    const labels = document.querySelectorAll(".bar-labels span");
    if (labels.length === 3) {{
      // Compute data range for meaningful labels
      const vs = ANALYSIS.map(a => a[meta.field] || 0).filter(v => isFinite(v));
      if (vs.length) {{
        let mn = Infinity, mx = -Infinity;
        for (const v of vs) {{ if (v < mn) mn = v; if (v > mx) mx = v; }}
        const mid = (mn + mx) / 2;
        labels[0].innerText = meta.fmt(mn);
        labels[1].innerText = meta.fmt(mid);
        labels[2].innerText = meta.fmt(mx);
      }} else {{
        labels[0].innerText = "Low"; labels[1].innerText = "Med"; labels[2].innerText = "High";
      }}
    }}
  }} else {{
    titleEl.innerText = modeText;
    const labels = document.querySelectorAll(".bar-labels span");
    if (labels.length === 3) {{
      labels[0].innerText = "Low"; labels[1].innerText = "Medium"; labels[2].innerText = "High";
    }}
  }}
}}

function updateAnalysisDescription() {{
  const meta = analysisMeta[currentMode];
  if (!meta) return;
  document.getElementById("analysisDescription").innerHTML =
    `<b>${{meta.title}}</b><br><b>Built from:</b> ${{meta.built_from}}<br><b>Purpose:</b> ${{meta.purpose}}`;
}}

function buildTerrain() {{
  if (!TERRAIN || !TERRAIN.length || !TERRAIN[0].length) return;

  // TERRAIN[x_idx][y_idx]: x_idx goes xMin->xMax, y_idx goes yMin->yMax (north-positive)
  // Convention used throughout this viewer:
  //   world X = local x (east positive)
  //   world Z = -(local y)   <-- north maps to world -Z (away from default camera)
  // We build the plane natural, then MIRROR it in Z via negative scale so the
  // terrain matches the "north = -Z" convention used by voxels/analysis/roads.

  const cols = TERRAIN.length;       // X samples
  const rows = TERRAIN[0].length;    // Y samples
  const width = (cols - 1) * TERRAIN_STEP;
  const height = (rows - 1) * TERRAIN_STEP;

  const geo = new THREE.PlaneGeometry(width, height, cols - 1, rows - 1);
  geo.rotateX(-Math.PI / 2);

  const pos = geo.attributes.position;
  let idx = 0;

  // PlaneGeometry (pre-rotate) fills row-major from local +Y (top) to -Y (bottom).
  // After rotateX(-PI/2): local +Y -> world -Z, local -Y -> world +Z.
  // So idx=0..cols-1 vertices sit at world -Z (which in our convention = northern).
  // We want northern data (max y_idx) there, so use TERRAIN[j][rows-1-i].
  for (let i = 0; i < rows; i++) {{
    for (let j = 0; j < cols; j++) {{
      const yIdx = rows - 1 - i;
      const z = TERRAIN[j][yIdx] || 0;
      pos.setY(idx, z);
      idx++;
    }}
  }}

  geo.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({{
    color: 0x6b7280,
    roughness: 0.95,
    metalness: 0.02,
    transparent: true,
    opacity: 0.92
  }});

  terrainMesh = new THREE.Mesh(geo, mat);
  scene.add(terrainMesh);
}}

function getTerrainHeightAtLocal(x, y) {{
  // Input: local coords where x=east-positive, y=north-positive.
  // World convention: world Z = -(local y). So at (world_x, world_z),
  // we have local x = world_x, local y = -world_z.
  // Callers of this function pass LOCAL coords (from JSON data), so we just
  // look up TERRAIN[x_idx][y_idx] directly.
  if (!TERRAIN || !TERRAIN.length || !TERRAIN[0].length) return 0;

  const cols = TERRAIN.length;
  const rows = TERRAIN[0].length;
  const width = (cols - 1) * TERRAIN_STEP;
  const height = (rows - 1) * TERRAIN_STEP;

  const minX = -width / 2;
  const minY = -height / 2;

  const col = Math.max(0, Math.min(cols - 1, Math.round((x - minX) / TERRAIN_STEP)));
  const row = Math.max(0, Math.min(rows - 1, Math.round((y - minY) / TERRAIN_STEP)));

  return (TERRAIN[col] && TERRAIN[col][row] !== undefined) ? TERRAIN[col][row] : 0;
}}

function scoreColor(v) {{
  const c = new THREE.Color();
  if (v < 0.33) {{
    c.lerpColors(new THREE.Color(0x1d4ed8), new THREE.Color(0x16a34a), v / 0.33);
  }} else if (v < 0.66) {{
    c.lerpColors(new THREE.Color(0x16a34a), new THREE.Color(0xca8a04), (v - 0.33) / 0.33);
  }} else {{
    c.lerpColors(new THREE.Color(0xca8a04), new THREE.Color(0xdc2626), (v - 0.66) / 0.34);
  }}
  return c;
}}

function adjustedValue(base, mode) {{
  let v = base || 0;

  const radiusFactor = Math.max(0.75, Math.min(1.25, viewRadius / 250.0));
  const sunFactor = Math.sin((sunElevation * Math.PI) / 180.0);
  const azFactor = 0.85 + 0.15 * Math.cos((sunAzimuth - 135.0) * Math.PI / 180.0);

  if (mode === "solar") {{
    v = v * sunFactor * azFactor;
  }} else if (mode === "shading") {{
    v = v * (1.15 - sunFactor * 0.35);
  }} else if (mode === "skyview") {{
    v = v * (1.0 / radiusFactor);
  }} else if (mode === "greenview") {{
    v = v * Math.sqrt(radiusFactor);
  }} else if (mode === "comfort") {{
    v = v * (1.05 - sunFactor * 0.15) * Math.sqrt(radiusFactor);
  }} else if (mode === "landmark") {{
    v = v * (1.0 / Math.sqrt(radiusFactor));
  }} else if (mode === "composite") {{
    v = v * (0.95 + 0.05 * radiusFactor) * (0.95 + 0.05 * azFactor);
  }}

  return Math.max(0, Math.min(1, v));
}}

function getVoxelVisualY(v, size) {{
  const ground = getTerrainHeightAtLocal(v.x, v.y);

  if (v.type === "building") {{
    return (v.z || 0) + size / 2;
  }}
  if (v.type === "vegetation") {{
    return ground + size / 2;
  }}
  if (v.type === "canopy") {{
    return ground + (v.z || 0) + size / 2;
  }}
  return ground + (v.z || 0) + size / 2;
}}

function buildVoxels() {{
  voxelGroup = new THREE.Group();
  const size = 10;
  const geo = new THREE.BoxGeometry(size * 0.9, size * 0.9, size * 0.9);

  // Group voxels by type. Canopy is rendered as trees via buildTrees(), not here.
  const groups = {{ building: [], vegetation: [] }};
  for (let i = 0; i < VOXELS.length; i++) {{
    const v = VOXELS[i];
    const t = v.type || "building";
    if (groups[t]) groups[t].push(i);
  }}

  voxelMeshes = {{}};
  voxelIndexMap = {{}};

  const dummy = new THREE.Object3D();

  for (const t of Object.keys(groups)) {{
    const idxList = groups[t];
    if (!idxList.length) continue;

    const mat = new THREE.MeshStandardMaterial({{
      color: 0xffffff,
      roughness: 0.55,
      metalness: 0.08
    }});

    const mesh = new THREE.InstancedMesh(geo, mat, idxList.length);
    mesh.userData.voxType = t;

    for (let k = 0; k < idxList.length; k++) {{
      const vi = idxList[k];
      const v = VOXELS[vi];
      dummy.position.set(v.x, getVoxelVisualY(v, size), -v.y);
      dummy.updateMatrix();
      mesh.setMatrixAt(k, dummy.matrix);

      let col;
      if (t === "vegetation") {{
        col = new THREE.Color(0x22c55e);
      }} else {{
        col = scoreColor(adjustedValue(v[currentMode] || 0, currentMode));
      }}
      mesh.setColorAt(k, col);
    }}

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

    voxelMeshes[t] = mesh;
    voxelIndexMap[t] = idxList;
    voxelGroup.add(mesh);
  }}

  scene.add(voxelGroup);
}}

function buildSolids() {{
  solidGroup = new THREE.Group();
  solidMeshes = [];

  if (!SOLIDS || !SOLIDS.length) {{
    scene.add(solidGroup);
    return;
  }}

  for (let i = 0; i < SOLIDS.length; i++) {{
    const s = SOLIDS[i];
    if (!s.parts || !s.parts.length) continue;

    for (const part of s.parts) {{
      if (!part.outer || part.outer.length < 3) continue;

      const shape = new THREE.Shape();
      shape.moveTo(part.outer[0][0], part.outer[0][1]);
      for (let k = 1; k < part.outer.length; k++) {{
        shape.lineTo(part.outer[k][0], part.outer[k][1]);
      }}
      shape.closePath();

      if (part.holes && part.holes.length) {{
        for (const hole of part.holes) {{
          if (!hole || hole.length < 3) continue;
          const hpath = new THREE.Path();
          hpath.moveTo(hole[0][0], hole[0][1]);
          for (let k = 1; k < hole.length; k++) {{
            hpath.lineTo(hole[k][0], hole[k][1]);
          }}
          hpath.closePath();
          shape.holes.push(hpath);
        }}
      }}

      const extrudeSettings = {{
        depth: Math.max(0.5, s.h),
        bevelEnabled: false,
        steps: 1
      }};

      let geo;
      try {{
        geo = new THREE.ExtrudeGeometry(shape, extrudeSettings);
      }} catch (e) {{
        continue;
      }}

      // Shape is defined in XY plane, extrude goes along +Z.
      // World uses Y vertical, so rotate so extrude direction maps to world +Y.
      geo.rotateX(-Math.PI / 2);

      const col = scoreColor(adjustedValue(s[currentMode] || 0, currentMode));
      const mat = new THREE.MeshStandardMaterial({{
        color: col,
        roughness: 0.65,
        metalness: 0.05,
        flatShading: false
      }});

      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.y = s.base || 0;
      mesh.userData.solidIndex = i;

      solidGroup.add(mesh);
      solidMeshes.push(mesh);
    }}
  }}

  scene.add(solidGroup);
}}

function recolorSolids() {{
  if (!solidMeshes || !solidMeshes.length) return;
  for (const mesh of solidMeshes) {{
    const idx = mesh.userData.solidIndex;
    const s = SOLIDS[idx];
    if (!s) continue;
    const col = scoreColor(adjustedValue(s[currentMode] || 0, currentMode));
    mesh.material.color.copy(col);
  }}
}}

function buildVegetationAndCanopyVoxels() {{
  // Solid mode: buildings are extruded, vegetation as voxels, canopy as trees (buildTrees)
  voxelGroup = new THREE.Group();
  voxelMeshes = {{}};
  voxelIndexMap = {{}};

  const size = 10;
  const geo = new THREE.BoxGeometry(size * 0.9, size * 0.9, size * 0.9);

  const groups = {{ vegetation: [] }};
  for (let i = 0; i < VOXELS.length; i++) {{
    const v = VOXELS[i];
    const t = v.type;
    if (groups[t]) groups[t].push(i);
  }}

  const dummy = new THREE.Object3D();

  for (const t of Object.keys(groups)) {{
    const idxList = groups[t];
    if (!idxList.length) continue;

    const mat = new THREE.MeshStandardMaterial({{
      color: 0xffffff,
      roughness: 0.55,
      metalness: 0.08
    }});

    const mesh = new THREE.InstancedMesh(geo, mat, idxList.length);
    mesh.userData.voxType = t;

    const fixedCol = new THREE.Color(0x22c55e);

    for (let k = 0; k < idxList.length; k++) {{
      const vi = idxList[k];
      const v = VOXELS[vi];
      dummy.position.set(v.x, getVoxelVisualY(v, size), -v.y);
      dummy.updateMatrix();
      mesh.setMatrixAt(k, dummy.matrix);
      mesh.setColorAt(k, fixedCol);
    }}

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

    voxelMeshes[t] = mesh;
    voxelIndexMap[t] = idxList;
    voxelGroup.add(mesh);
  }}

  scene.add(voxelGroup);
}}

function buildAnalysis() {{
  analysisGroup = new THREE.Group();
  if (!ANALYSIS.length) {{
    scene.add(analysisGroup);
    return;
  }}

  const geo = new THREE.SphereGeometry(4, 8, 8);
  const mat = new THREE.MeshStandardMaterial({{
    color: 0xffffff,
    emissive: 0x000000,
    emissiveIntensity: 0.15,
    roughness: 0.4
  }});

  analysisMesh = new THREE.InstancedMesh(geo, mat, ANALYSIS.length);
  const dummy = new THREE.Object3D();
  const col = new THREE.Color();

  for (let i = 0; i < ANALYSIS.length; i++) {{
    const a = ANALYSIS[i];
    const terrainY = (a.z !== undefined && a.z !== null) ? a.z : getTerrainHeightAtLocal(a.x, a.y);
    dummy.position.set(a.x, terrainY + 6, -a.y);
    dummy.updateMatrix();
    analysisMesh.setMatrixAt(i, dummy.matrix);

    col.copy(scoreColor(adjustedValue(a[currentMode] || 0, currentMode)));
    analysisMesh.setColorAt(i, col);
  }}

  analysisMesh.instanceMatrix.needsUpdate = true;
  if (analysisMesh.instanceColor) analysisMesh.instanceColor.needsUpdate = true;

  analysisGroup.add(analysisMesh);
  scene.add(analysisGroup);
}}

function buildRoads() {{
  roadsGroup = new THREE.Group();
  if (!ROADS || !ROADS.length) {{
    scene.add(roadsGroup);
    return;
  }}

  // Render each road as a flat ribbon following terrain. Width is proportional
  // to the road's width attribute in meters. Color: warm off-white asphalt tone.
  const mat = new THREE.MeshStandardMaterial({{
    color: 0xcbd5e1,
    roughness: 0.85,
    metalness: 0.05,
    side: THREE.DoubleSide
  }});

  const lift = 0.6; // meters above terrain to prevent z-fighting

  for (const road of ROADS) {{
    if (!road.pts || road.pts.length < 2) continue;
    const width = road.width || 6.0;
    const halfW = width / 2;

    // Build ribbon by offsetting each segment perpendicular, densified across segments
    const positions = [];
    const indices = [];

    for (let i = 0; i < road.pts.length; i++) {{
      const [x, y] = road.pts[i];
      // Compute segment direction (average of incoming + outgoing for smooth miter)
      let dx = 0, dy = 0, count = 0;
      if (i > 0) {{
        dx += x - road.pts[i-1][0];
        dy += y - road.pts[i-1][1];
        count++;
      }}
      if (i < road.pts.length - 1) {{
        dx += road.pts[i+1][0] - x;
        dy += road.pts[i+1][1] - y;
        count++;
      }}
      if (count > 0) {{ dx /= count; dy /= count; }}
      const len = Math.hypot(dx, dy);
      if (len < 1e-6) {{
        // Can't compute normal; skip but preserve topology
        positions.push(x, getTerrainHeightAtLocal(x, y) + lift, -y);
        positions.push(x, getTerrainHeightAtLocal(x, y) + lift, -y);
        continue;
      }}
      // Perpendicular (normalized): rotate (dx,dy) by 90deg -> (-dy, dx)
      const nx = -dy / len;
      const ny = dx / len;

      const xL = x + nx * halfW;
      const yL = y + ny * halfW;
      const xR = x - nx * halfW;
      const yR = y - ny * halfW;

      const gL = getTerrainHeightAtLocal(xL, yL) + lift;
      const gR = getTerrainHeightAtLocal(xR, yR) + lift;

      // World Z = -(local y) — north maps to world -Z
      positions.push(xL, gL, -yL);
      positions.push(xR, gR, -yR);
    }}

    // Build triangle indices for strip
    for (let i = 0; i < road.pts.length - 1; i++) {{
      const a = i * 2;
      const b = i * 2 + 1;
      const c = (i + 1) * 2;
      const d = (i + 1) * 2 + 1;
      indices.push(a, b, c);
      indices.push(b, d, c);
    }}

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();

    const mesh = new THREE.Mesh(geo, mat);
    roadsGroup.add(mesh);
  }}

  scene.add(roadsGroup);
}}

function buildTrees() {{
  // Render canopy as actual tree shapes: trunk cylinder + crown sphere.
  // Data source: TREES_DATA (canopy samples from Python, 1 sample = 1 tree).
  // This is INDEPENDENT of VOXELS so trees render regardless of canopy_mode
  // (analysis-only OR voxel+analysis). No deduplication needed because
  // each sample already represents one distinct tree location.
  treesGroup = new THREE.Group();
  treesTrunkMesh = null;
  treesCrownMesh = null;

  if (!TREES_DATA || !TREES_DATA.length) {{
    console.log("[buildTrees] no TREES_DATA - no canopy samples provided");
    scene.add(treesGroup);
    return;
  }}

  const trees = TREES_DATA;
  console.log("[buildTrees] rendering", trees.length, "trees from canopy samples");

  // Reusable geometries - low-poly for performance
  const trunkGeo = new THREE.CylinderGeometry(0.35, 0.45, 1.0, 6);  // unit-height, will be scaled
  const crownGeo = new THREE.SphereGeometry(1.0, 8, 6);  // unit-radius, will be scaled

  const trunkMat = new THREE.MeshStandardMaterial({{
    color: 0x5d4030,  // warm dark brown
    roughness: 0.95,
    metalness: 0.02
  }});
  const crownMat = new THREE.MeshStandardMaterial({{
    color: 0x2e7d32,  // saturated forest green
    roughness: 0.85,
    metalness: 0.03
  }});

  treesTrunkMesh = new THREE.InstancedMesh(trunkGeo, trunkMat, trees.length);
  treesCrownMesh = new THREE.InstancedMesh(crownGeo, crownMat, trees.length);

  const dummy = new THREE.Object3D();

  for (let i = 0; i < trees.length; i++) {{
    const tr = trees[i];
    const totalH = Math.max(3, Math.min(35, tr.h));  // clamp to sensible bounds
    const trunkH = totalH * 0.55;
    const crownH = totalH * 0.55;  // crown spans upper half, with overlap
    const crownRadius = Math.max(1.2, Math.min(5.0, totalH * 0.28));
    const trunkRadius = Math.max(0.18, crownRadius * 0.12);

    const ground = getTerrainHeightAtLocal(tr.x, tr.y);
    const worldX = tr.x;
    const worldZ = -tr.y;  // north mapping convention

    // Trunk: centered at trunkH/2 above ground
    dummy.position.set(worldX, ground + trunkH / 2, worldZ);
    dummy.scale.set(trunkRadius / 0.4, trunkH, trunkRadius / 0.4);
    dummy.rotation.set(0, 0, 0);
    dummy.updateMatrix();
    treesTrunkMesh.setMatrixAt(i, dummy.matrix);

    // Crown: centered at trunkH + crownH*0.35 above ground
    // Slight pseudo-random rotation per tree for organic feel
    const rotY = (Math.sin(i * 7.31) + 1) * Math.PI;
    dummy.position.set(worldX, ground + trunkH + crownH * 0.35, worldZ);
    dummy.scale.set(crownRadius, crownH * 0.75, crownRadius);
    dummy.rotation.set(0, rotY, 0);
    dummy.updateMatrix();
    treesCrownMesh.setMatrixAt(i, dummy.matrix);
  }}

  treesTrunkMesh.instanceMatrix.needsUpdate = true;
  treesCrownMesh.instanceMatrix.needsUpdate = true;

  treesGroup.add(treesTrunkMesh);
  treesGroup.add(treesCrownMesh);
  scene.add(treesGroup);
}}

function recolorVoxels() {{
  if (!voxelMeshes) return;

  // Only building voxels react to mode changes - vegetation & canopy stay fixed colors
  const mesh = voxelMeshes["building"];
  const idxList = voxelIndexMap["building"];
  if (!mesh || !idxList) return;

  const col = new THREE.Color();
  for (let k = 0; k < idxList.length; k++) {{
    const v = VOXELS[idxList[k]];
    col.copy(scoreColor(adjustedValue(v[currentMode] || 0, currentMode)));
    mesh.setColorAt(k, col);
  }}
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}}

function recolorAnalysis() {{
  if (!analysisMesh) return;

  const col = new THREE.Color();
  for (let i = 0; i < ANALYSIS.length; i++) {{
    const a = ANALYSIS[i];
    col.copy(scoreColor(adjustedValue(a[currentMode] || 0, currentMode)));
    analysisMesh.setColorAt(i, col);
  }}
  if (analysisMesh.instanceColor) analysisMesh.instanceColor.needsUpdate = true;
}}

function updateDashboard() {{
  document.getElementById("voxelCount").innerText = VOXELS.length.toLocaleString();
  document.getElementById("analysisCount").innerText = ANALYSIS.length.toLocaleString();

  // Determine what to aggregate: normalized score OR physical unit value
  const meta = physicalMeta[currentMode];
  const usePhysical = (displayMode === "physical" && meta && meta.field);

  const vals = ANALYSIS.map(a => {{
    if (usePhysical) return a[meta.field] || 0;
    return adjustedValue(a[currentMode] || 0, currentMode);
  }});

  let avg = 0, max = 0, min = 0, hot = 0;
  if (vals.length) {{
    let sum = 0, mx = -Infinity, mn = Infinity;
    // "Hot" threshold depends on mode in physical units
    let hotThreshold = 0.66;
    if (usePhysical) {{
      if (currentMode === "solar") hotThreshold = 700;          // W/m² high exposure
      else if (currentMode === "greenview") hotThreshold = 40;  // % high greenery
      else if (currentMode === "skyview") hotThreshold = 0.65;  // SVF open sky
      else hotThreshold = 0.66;
    }}
    for (let i = 0; i < vals.length; i++) {{
      const v = vals[i];
      sum += v;
      if (v > mx) mx = v;
      if (v < mn) mn = v;
      if (v >= hotThreshold) hot++;
    }}
    avg = sum / vals.length;
    max = mx;
    min = mn;
  }}
  const hotspots = vals.length ? (hot / vals.length) * 100 : 0;

  // Format depending on mode
  const fmt = usePhysical
    ? ((v) => meta.fmt(v))
    : ((v) => v.toFixed(2));

  document.getElementById("avgScore").innerText = fmt(avg);
  document.getElementById("maxScore").innerText = fmt(max);
  document.getElementById("minScore").innerText = fmt(min);
  document.getElementById("hotspotPct").innerText = hotspots.toFixed(1) + "%";

  // Physical readout strip below Mode selector
  const readoutEl = document.getElementById("physicalReadout");
  if (readoutEl) {{
    if (meta && meta.field) {{
      readoutEl.innerText = "physical: " + meta.unit + " · ref: " + meta.ref;
    }} else {{
      readoutEl.innerText = "score 0–1 only (no established physical unit)";
    }}
  }}

  const terrainVals = [];
  for (let i = 0; i < TERRAIN.length; i++) {{
    for (let j = 0; j < TERRAIN[i].length; j++) {{
      const v = TERRAIN[i][j];
      if (v !== null && v !== undefined && !isNaN(v)) {{
        terrainVals.push(v);
      }}
    }}
  }}

  let tMin = 0, tMax = 0;
  if (terrainVals.length) {{
    let mx = -Infinity, mn = Infinity;
    for (let i = 0; i < terrainVals.length; i++) {{
      const v = terrainVals[i];
      if (v > mx) mx = v;
      if (v < mn) mn = v;
    }}
    tMin = mn;
    tMax = mx;
  }}
  document.getElementById("terrainMin").innerText = tMin.toFixed(1);
  document.getElementById("terrainMax").innerText = tMax.toFixed(1);

  const buildingCount = (BUILDING_MODE === "solid")
    ? SOLIDS.length
    : VOXELS.filter(v => v.type === "building").length;
  const vegetationCount = VOXELS.filter(v => v.type === "vegetation").length;
  const canopyCount = (TREES_DATA && TREES_DATA.length) || VOXELS.filter(v => v.type === "canopy").length;

  document.getElementById("buildingCount").innerText = buildingCount.toLocaleString();
  document.getElementById("vegetationCount").innerText = vegetationCount.toLocaleString();
  document.getElementById("canopyCount").innerText = canopyCount.toLocaleString();
}}

function toggleLayer(name) {{
  if (name === "terrain" && terrainMesh) {{
    terrainMesh.visible = !terrainMesh.visible;
    document.getElementById("btnTerrain").classList.toggle("toggle-on", terrainMesh.visible);
  }}
  if (name === "voxels") {{
    // In solid mode, this toggles the extruded buildings group.
    // In voxel mode, this toggles the full voxel group.
    // In both modes, trees follow voxel/building visibility.
    if (BUILDING_MODE === "solid") {{
      if (solidGroup) {{
        solidGroup.visible = !solidGroup.visible;
        if (voxelGroup) voxelGroup.visible = solidGroup.visible;
        if (treesGroup) treesGroup.visible = solidGroup.visible;
        document.getElementById("btnVoxels").classList.toggle("toggle-on", solidGroup.visible);
      }}
    }} else {{
      if (voxelGroup) {{
        voxelGroup.visible = !voxelGroup.visible;
        if (treesGroup) treesGroup.visible = voxelGroup.visible;
        document.getElementById("btnVoxels").classList.toggle("toggle-on", voxelGroup.visible);
      }}
    }}
  }}
  if (name === "analysis" && analysisGroup) {{
    analysisGroup.visible = !analysisGroup.visible;
    document.getElementById("btnAnalysis").classList.toggle("toggle-on", analysisGroup.visible);
  }}
  if (name === "roads" && roadsGroup) {{
    roadsGroup.visible = !roadsGroup.visible;
    document.getElementById("btnRoads").classList.toggle("toggle-on", roadsGroup.visible);
  }}
}}

function resetCamera() {{
  const box = new THREE.Box3();
  if (voxelGroup) box.expandByObject(voxelGroup);
  if (solidGroup) box.expandByObject(solidGroup);
  if (roadsGroup) box.expandByObject(roadsGroup);
  if (treesGroup) box.expandByObject(treesGroup);
  if (terrainMesh) box.expandByObject(terrainMesh);

  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);

  const maxDim = Math.max(size.x, size.y, size.z, 200);
  camera.position.set(center.x + maxDim * 0.8, center.y + maxDim * 0.6, center.z + maxDim * 0.8);
  controls.target.copy(center);
  controls.update();
}}

function onResize() {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  if (typeof resizeMinimap === "function") resizeMinimap();
}}

// -----------------------------------------------------------------------------
// Minimap (Native Canvas 2D) - top-down projection of local coords, no tiles.
// Renders: boundary outline, building footprints colored by current mode,
// road network, analysis points, and a live viewport rectangle synced to 3D.
// State variables are declared at the top of the script (near voxelGroup etc.)
// to avoid TDZ errors when buildMinimap() is invoked from buildScene().
// -----------------------------------------------------------------------------

function getLocalExtentX() {{
  if (_cachedExtX !== null) return _cachedExtX;
  if (TERRAIN && TERRAIN.length && TERRAIN[0]) {{
    _cachedExtX = (TERRAIN.length - 1) * TERRAIN_STEP;
    return _cachedExtX;
  }}
  return 1000;
}}
function getLocalExtentY() {{
  if (_cachedExtY !== null) return _cachedExtY;
  if (TERRAIN && TERRAIN.length && TERRAIN[0]) {{
    _cachedExtY = (TERRAIN[0].length - 1) * TERRAIN_STEP;
    return _cachedExtY;
  }}
  return 1000;
}}

function buildMinimap() {{
  const el = document.getElementById("minimap");
  if (!el) {{
    console.error("[buildMinimap] #minimap element not found");
    return;
  }}
  el.innerHTML = "";
  minimapCanvas = document.createElement("canvas");
  minimapCanvas.style.width = "100%";
  minimapCanvas.style.height = "100%";
  minimapCanvas.style.display = "block";
  minimapCanvas.style.cursor = "grab";
  el.appendChild(minimapCanvas);
  minimapCtx = minimapCanvas.getContext("2d");

  // Log actual container size for debugging
  const parentRect = el.getBoundingClientRect();
  console.log("[buildMinimap] container size:", parentRect.width, "x", parentRect.height);

  // If container has 0 size (layout race), retry once on next frame
  if (parentRect.width < 2 || parentRect.height < 2) {{
    console.warn("[buildMinimap] container has 0 size, scheduling retry");
    requestAnimationFrame(() => {{
      const r2 = el.getBoundingClientRect();
      console.log("[buildMinimap] retry container size:", r2.width, "x", r2.height);
      resizeMinimap();
      fitMinimapToExtent();
      minimapInitialViewport = {{ ...minimapViewport }};
      drawMinimap();
    }});
  }} else {{
    resizeMinimap();
    fitMinimapToExtent();
    minimapInitialViewport = {{ ...minimapViewport }};
  }}

  // Pan drag
  minimapCanvas.addEventListener("mousedown", (e) => {{
    minimapDragging = true;
    minimapDragStart = {{ x: e.offsetX, y: e.offsetY, ox: minimapViewport.offsetX, oy: minimapViewport.offsetY }};
    minimapCanvas.style.cursor = "grabbing";
  }});
  window.addEventListener("mouseup", () => {{
    minimapDragging = false;
    if (minimapCanvas) minimapCanvas.style.cursor = "grab";
  }});
  minimapCanvas.addEventListener("mousemove", (e) => {{
    if (minimapDragging && minimapDragStart) {{
      minimapViewport.offsetX = minimapDragStart.ox + (e.offsetX - minimapDragStart.x);
      minimapViewport.offsetY = minimapDragStart.oy + (e.offsetY - minimapDragStart.y);
      drawMinimap();
    }}
    const world = canvasToLocal(e.offsetX, e.offsetY);
    if (world) {{
      const ll = localToLonLat(world.x, world.y);
      const el2 = document.getElementById("minimap-coords");
      if (ll) el2.innerText = ll[0].toFixed(5) + ", " + ll[1].toFixed(5);
      else el2.innerText = world.x.toFixed(0) + "m, " + world.y.toFixed(0) + "m";
    }}
  }});
  // Wheel zoom
  minimapCanvas.addEventListener("wheel", (e) => {{
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoomMinimapAt(e.offsetX, e.offsetY, factor);
  }}, {{ passive: false }});
  // Click = pan 3D camera target
  let mouseDownPos = null;
  minimapCanvas.addEventListener("mousedown", (e) => {{ mouseDownPos = {{x: e.offsetX, y: e.offsetY}}; }});
  minimapCanvas.addEventListener("click", (e) => {{
    if (mouseDownPos && Math.hypot(e.offsetX - mouseDownPos.x, e.offsetY - mouseDownPos.y) > 4) return;
    const local = canvasToLocal(e.offsetX, e.offsetY);
    if (local) {{
      const ty = getTerrainHeightAtLocal(local.x, local.y);
      // World Z = -(local y)
      controls.target.set(local.x, ty, -local.y);
      controls.update();
    }}
  }});

  // Sync camera -> minimap viewport rectangle
  let pending = false;
  controls.addEventListener("change", () => {{
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {{
      pending = false;
      drawMinimap();
    }});
  }});

  document.getElementById("statusMap").innerHTML = `Map: <span class="status-ok">OK</span>`;
  drawMinimap();
}}

function resizeMinimap() {{
  if (!minimapCanvas) return;
  let rect = minimapCanvas.getBoundingClientRect();
  // Fallback: if canvas itself reports 0, use parent container dimensions
  if (rect.width < 2 || rect.height < 2) {{
    const parent = minimapCanvas.parentElement;
    if (parent) {{
      const pr = parent.getBoundingClientRect();
      rect = {{ width: pr.width || parent.clientWidth || 300, height: pr.height || parent.clientHeight || 200 }};
    }} else {{
      rect = {{ width: 300, height: 200 }};
    }}
  }}
  const dpr = window.devicePixelRatio || 1;
  minimapCanvas.width = Math.max(1, Math.floor(rect.width * dpr));
  minimapCanvas.height = Math.max(1, Math.floor(rect.height * dpr));
  minimapCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  console.log("[resizeMinimap] canvas set to", minimapCanvas.width, "x", minimapCanvas.height, "(css", rect.width, "x", rect.height, ")");
  drawMinimap();
}}

function fitMinimapToExtent() {{
  if (!minimapCanvas) return;
  let rect = minimapCanvas.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) {{
    const parent = minimapCanvas.parentElement;
    if (parent) {{
      const pr = parent.getBoundingClientRect();
      rect = {{ width: pr.width || parent.clientWidth || 300, height: pr.height || parent.clientHeight || 200 }};
    }} else {{
      rect = {{ width: 300, height: 200 }};
    }}
  }}
  const extX = getLocalExtentX();
  const extY = getLocalExtentY();
  const padding = 12;
  const sx = (rect.width - padding * 2) / extX;
  const sy = (rect.height - padding * 2) / extY;
  minimapViewport.scale = Math.max(0.0001, Math.min(sx, sy));
  minimapViewport.offsetX = rect.width / 2;
  minimapViewport.offsetY = rect.height / 2;
  console.log("[fitMinimapToExtent] scale=", minimapViewport.scale, "ext=", extX, "x", extY);
}}

function zoomMinimapAt(cx, cy, factor) {{
  // Keep point (cx,cy) fixed during zoom
  const local = canvasToLocal(cx, cy);
  minimapViewport.scale *= factor;
  minimapViewport.scale = Math.max(0.01, Math.min(100, minimapViewport.scale));
  if (local) {{
    // After scale change, recompute offset so the same local point is at (cx,cy)
    minimapViewport.offsetX = cx - local.x * minimapViewport.scale;
    // Note: Y flipped for screen coords, north-up
    minimapViewport.offsetY = cy + local.y * minimapViewport.scale;
  }}
  drawMinimap();
}}

function localToCanvas(lx, ly) {{
  // North-up: larger local y (northern) -> smaller screen y (upward)
  return {{
    x: minimapViewport.offsetX + lx * minimapViewport.scale,
    y: minimapViewport.offsetY - ly * minimapViewport.scale
  }};
}}

function canvasToLocal(cx, cy) {{
  return {{
    x: (cx - minimapViewport.offsetX) / minimapViewport.scale,
    y: (minimapViewport.offsetY - cy) / minimapViewport.scale
  }};
}}

function localToLonLat(lx, ly) {{
  if (!GEO_REF || !GEO_REF.valid || !GEO_REF.corners) return null;
  const sw = GEO_REF.corners.sw, se = GEO_REF.corners.se;
  const nw = GEO_REF.corners.nw, ne = GEO_REF.corners.ne;
  const extX = getLocalExtentX(), extY = getLocalExtentY();
  const u = (lx + extX / 2) / extX;
  const v = (ly + extY / 2) / extY;
  const latA = sw[0] + (se[0] - sw[0]) * u;
  const latB = nw[0] + (ne[0] - nw[0]) * u;
  const lonA = sw[1] + (se[1] - sw[1]) * u;
  const lonB = nw[1] + (ne[1] - nw[1]) * u;
  return [latA + (latB - latA) * v, lonA + (lonB - lonA) * v];
}}

function drawMinimap() {{
  if (!minimapCtx || !minimapCanvas) return;
  try {{
    let rect = minimapCanvas.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) {{
      const parent = minimapCanvas.parentElement;
      if (parent) {{
        const pr = parent.getBoundingClientRect();
        rect = {{ width: pr.width || parent.clientWidth || 300, height: pr.height || parent.clientHeight || 200 }};
      }} else {{
        return;
      }}
    }}
    if (rect.width < 2 || rect.height < 2) return;
    const ctx = minimapCtx;

    // Background
    ctx.fillStyle = "#0b1730";
    ctx.fillRect(0, 0, rect.width, rect.height);

  // Subtle grid
  const gridStep = 100 * minimapViewport.scale;
  if (gridStep > 20 && gridStep < 200) {{
    ctx.strokeStyle = "rgba(100,120,150,0.08)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let gx = minimapViewport.offsetX % gridStep; gx < rect.width; gx += gridStep) {{
      ctx.moveTo(gx, 0); ctx.lineTo(gx, rect.height);
    }}
    for (let gy = minimapViewport.offsetY % gridStep; gy < rect.height; gy += gridStep) {{
      ctx.moveTo(0, gy); ctx.lineTo(rect.width, gy);
    }}
    ctx.stroke();
  }}

  // Boundary rectangle (extent of data)
  const extX = getLocalExtentX(), extY = getLocalExtentY();
  const sw = localToCanvas(-extX/2, -extY/2);
  const ne = localToCanvas(extX/2, extY/2);
  ctx.strokeStyle = "rgba(96,165,250,0.7)";
  ctx.setLineDash([4, 3]);
  ctx.lineWidth = 1.2;
  ctx.strokeRect(sw.x, ne.y, ne.x - sw.x, sw.y - ne.y);
  ctx.setLineDash([]);

  // ---------------- Heatmap layer from analysis points ----------------
  // Renders continuous heat surface via gaussian splatting with additive
  // blending. Radius is proportional to minimap scale so splats merge
  // smoothly into a surface. Color follows current analysis mode.
  if (heatmapEnabled && ANALYSIS && ANALYSIS.length) {{
    // Estimate analysis step from data spacing (cached)
    if (!window._heatmapStep) {{
      // Use median of nearest-neighbor x distances as step estimate
      // (fast approximation: first few points)
      let step = 80;
      if (ANALYSIS.length >= 2) {{
        const xs = ANALYSIS.slice(0, Math.min(50, ANALYSIS.length)).map(a => a.x).sort((a,b) => a-b);
        const diffs = [];
        for (let i = 1; i < xs.length; i++) {{
          const d = xs[i] - xs[i-1];
          if (d > 0.5) diffs.push(d);
        }}
        if (diffs.length) {{
          diffs.sort((a,b) => a-b);
          step = diffs[Math.floor(diffs.length / 2)];
        }}
      }}
      window._heatmapStep = step;
    }}
    const step = window._heatmapStep;
    // Splat radius in canvas pixels — sized so splats overlap smoothly
    const radiusPx = Math.max(6, step * minimapViewport.scale * 1.4);

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.globalAlpha = 0.55;

    for (const a of ANALYSIS) {{
      const v = adjustedValue(a[currentMode] || 0, currentMode);
      if (v <= 0.001) continue;  // skip near-zero for performance
      const p = localToCanvas(a.x, a.y);
      // Cull if far off-screen
      if (p.x < -radiusPx || p.x > rect.width + radiusPx ||
          p.y < -radiusPx || p.y > rect.height + radiusPx) continue;

      const col = scoreColorHex(v);
      const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radiusPx);
      // Intensity weighted by score so low-score points don't wash out
      const intensity = Math.min(1, v * 1.2).toFixed(3);
      grad.addColorStop(0, col + Math.floor(intensity * 255).toString(16).padStart(2, '0'));
      grad.addColorStop(0.6, col + Math.floor(intensity * 60).toString(16).padStart(2, '0'));
      grad.addColorStop(1, col + "00");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radiusPx, 0, Math.PI * 2);
      ctx.fill();
    }}

    ctx.restore();
  }}

  // Buildings (solid mode) OR analysis points (voxel mode)
  if (BUILDING_MODE === "solid" && SOLIDS && SOLIDS.length) {{
    for (const s of SOLIDS) {{
      const v = adjustedValue(s[currentMode] || 0, currentMode);
      const hex = scoreColorHex(v);
      for (const part of s.parts) {{
        if (!part.outer || part.outer.length < 3) continue;
        ctx.fillStyle = hex;
        ctx.strokeStyle = "rgba(0,0,0,0.25)";
        ctx.lineWidth = 0.5;
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        for (let i = 0; i < part.outer.length; i++) {{
          const p = localToCanvas(part.outer[i][0], part.outer[i][1]);
          if (i === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        }}
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.globalAlpha = 1;
      }}
    }}
  }} else if (ANALYSIS && ANALYSIS.length) {{
    for (const a of ANALYSIS) {{
      const v = adjustedValue(a[currentMode] || 0, currentMode);
      const hex = scoreColorHex(v);
      const p = localToCanvas(a.x, a.y);
      ctx.fillStyle = hex;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
      ctx.fill();
    }}
  }}

  // Roads
  if (ROADS && ROADS.length) {{
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const r of ROADS) {{
      if (!r.pts || r.pts.length < 2) continue;
      // Line width scales with road width attribute but capped for readability
      const wPx = Math.max(1.0, Math.min(6.0, r.width * minimapViewport.scale * 0.4));
      ctx.lineWidth = wPx;
      ctx.beginPath();
      for (let i = 0; i < r.pts.length; i++) {{
        const p = localToCanvas(r.pts[i][0], r.pts[i][1]);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }}
      ctx.stroke();
    }}
  }}

  // Camera viewport rectangle (frustum projected to ground)
  drawMinimapViewport();
  }} catch (e) {{
    console.error("[drawMinimap] error:", e);
  }}
}}

function drawMinimapViewport() {{
  if (!minimapCtx || typeof controls === "undefined") return;
  const baseY = controls.target.y || 0;
  const corners = frustumGroundCorners(baseY);
  const ctx = minimapCtx;

  if (corners && corners.length === 4) {{
    ctx.strokeStyle = "#f97316";
    ctx.fillStyle = "rgba(249,115,22,0.12)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < 4; i++) {{
      // World Z = -(local y), so local y = -world z
      const p = localToCanvas(corners[i].x, -corners[i].z);
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }}
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }}

  // Camera target crosshair (world Z -> local y)
  const t = localToCanvas(controls.target.x, -controls.target.z);
  ctx.strokeStyle = "#f97316";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(t.x - 6, t.y); ctx.lineTo(t.x + 6, t.y);
  ctx.moveTo(t.x, t.y - 6); ctx.lineTo(t.x, t.y + 6);
  ctx.stroke();
}}

function frustumGroundCorners(groundY) {{
  try {{
    const ndc = [[-1,-1],[1,-1],[1,1],[-1,1]];
    const out = [];
    for (const [nx, ny] of ndc) {{
      const v = new THREE.Vector3(nx, ny, 0.5).unproject(camera);
      const dir = v.sub(camera.position).normalize();
      if (Math.abs(dir.y) < 1e-6) return null;
      const t = (groundY - camera.position.y) / dir.y;
      if (t <= 0) return null;
      out.push({{
        x: camera.position.x + t * dir.x,
        z: camera.position.z + t * dir.z
      }});
    }}
    return out;
  }} catch (e) {{ return null; }}
}}

function drawMinimapBuildings() {{
  drawMinimap();
}}

function updateMinimapFromCamera() {{
  drawMinimap();
}}

function scoreColorHex(v) {{
  const c = scoreColor(v);
  const r = Math.round(c.r * 255), g = Math.round(c.g * 255), b = Math.round(c.b * 255);
  return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}}

function minimapReset() {{
  if (!minimapInitialViewport) return;
  minimapViewport = {{ ...minimapInitialViewport }};
  drawMinimap();
}}
function minimapFitExtent() {{
  fitMinimapToExtent();
  drawMinimap();
}}

// -----------------------------------------------------------------------------
// Export PNG - composite 3D canvas + minimap + legend into a single image
// -----------------------------------------------------------------------------

async function exportPNG() {{
  const statusEl = document.getElementById("exportStatus");
  const btn = document.getElementById("btnExport");
  btn.disabled = true;
  statusEl.innerText = "Rendering 3D...";

  try {{
    // 1. Force a fresh 3D render so preserveDrawingBuffer has current frame
    renderer.render(scene, camera);
    const threeDataUrl = renderer.domElement.toDataURL("image/png");

    // 2. Minimap is already a native canvas - grab data directly
    statusEl.innerText = "Capturing map...";
    let mapDataUrl = null;
    if (minimapCanvas) {{
      try {{
        drawMinimap();  // ensure latest frame
        mapDataUrl = minimapCanvas.toDataURL("image/png");
      }} catch (e) {{
        console.warn("Map capture failed:", e);
      }}
    }}

    // 3. Composite onto a final canvas
    statusEl.innerText = "Compositing...";
    await composePNG(threeDataUrl, mapDataUrl);

    statusEl.innerText = "Done ✓";
    setTimeout(() => {{ statusEl.innerText = ""; }}, 2500);
  }} catch (err) {{
    console.error(err);
    statusEl.innerText = "Export failed: " + err.message;
  }} finally {{
    btn.disabled = false;
  }}
}}

function composePNG(threeUrl, mapUrl) {{
  return new Promise((resolve, reject) => {{
    const W = 1920, H = 1080;
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");

    // Background
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#0b1a33");
    bg.addColorStop(1, "#060d1a");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    const threeImg = new Image();
    threeImg.onload = () => {{
      // 3D panel - left 65% of canvas
      const padding = 32;
      const threePanelW = Math.round(W * 0.65) - padding * 1.5;
      const threePanelH = H - padding * 2 - 80;  // leave space for footer
      drawRoundedImage(ctx, threeImg, padding, padding, threePanelW, threePanelH, 14);

      const drawSidePanel = () => {{
        const sideX = padding + threePanelW + padding;
        const sideW = W - sideX - padding;
        let cursorY = padding;

        // Title
        ctx.fillStyle = "#e5eefc";
        ctx.font = "700 28px Inter, sans-serif";
        ctx.textBaseline = "top";
        ctx.fillText(TITLE_STRING, sideX, cursorY);
        cursorY += 38;

        ctx.fillStyle = "#93c5fd";
        ctx.font = "500 14px Inter, sans-serif";
        const modeLabel = document.getElementById("modeSelect");
        const modeText = modeLabel ? modeLabel.options[modeLabel.selectedIndex].text : currentMode;
        ctx.fillText("Mode: " + modeText, sideX, cursorY);
        cursorY += 26;

        // Map panel
        if (mapUrl) {{
          const mapImg = new Image();
          mapImg.onload = () => {{
            // Smaller map: 0.60 aspect instead of 0.75 to free vertical space
            // for bar + radar charts below without clipping radar bottom labels
            const mapH = Math.round(sideW * 0.60);
            drawRoundedImage(ctx, mapImg, sideX, cursorY, sideW, mapH, 12);
            cursorY += mapH + 18;
            const legendEndY = drawLegendBlock(ctx, sideX, cursorY, sideW);
            const barsEndY = drawIndicatorBars(ctx, sideX, legendEndY + 12, sideW, 200);
            drawIndicatorRadar(ctx, sideX, barsEndY + 6, sideW, 260);
            drawFooter(ctx, W, H, padding);
            finalize();
          }};
          mapImg.onerror = () => {{
            const legendEndY = drawLegendBlock(ctx, sideX, cursorY, sideW);
            const barsEndY = drawIndicatorBars(ctx, sideX, legendEndY + 12, sideW, 200);
            drawIndicatorRadar(ctx, sideX, barsEndY + 6, sideW, 260);
            drawFooter(ctx, W, H, padding);
            finalize();
          }};
          mapImg.src = mapUrl;
        }} else {{
          // No map available, just legend + charts
          const legendEndY = drawLegendBlock(ctx, sideX, cursorY, sideW);
          const barsEndY = drawIndicatorBars(ctx, sideX, legendEndY + 12, sideW, 200);
          drawIndicatorRadar(ctx, sideX, barsEndY + 6, sideW, 260);
          drawFooter(ctx, W, H, padding);
          finalize();
        }}
      }};

      drawSidePanel();

      function finalize() {{
        const link = document.createElement("a");
        const safe = TITLE_STRING.replace(/[^a-z0-9]/gi, "_").toLowerCase();
        link.download = "voxcity_" + safe + "_" + Date.now() + ".png";
        link.href = canvas.toDataURL("image/png");
        link.click();
        resolve();
      }}
    }};
    threeImg.onerror = () => reject(new Error("3D image load failed"));
    threeImg.src = threeUrl;
  }});
}}

function drawRoundedImage(ctx, img, x, y, w, h, r) {{
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
  ctx.clip();
  // Fit image within box preserving aspect
  const ar = img.width / img.height;
  const boxAr = w / h;
  let dw, dh, dx, dy;
  if (ar > boxAr) {{ dh = h; dw = h * ar; dx = x - (dw - w) / 2; dy = y; }}
  else {{ dw = w; dh = w / ar; dx = x; dy = y - (dh - h) / 2; }}
  ctx.drawImage(img, dx, dy, dw, dh);
  ctx.restore();

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
  ctx.stroke();
}}

function drawLegendBlock(ctx, x, y, w) {{
  const modeLabel = document.getElementById("modeSelect");
  const modeText = modeLabel ? modeLabel.options[modeLabel.selectedIndex].text : currentMode;

  // Section label
  ctx.fillStyle = "#86a3cc";
  ctx.font = "600 11px Inter, sans-serif";
  ctx.fillText("LEGEND — " + modeText.toUpperCase(), x, y);
  y += 22;

  // Gradient bar
  const barW = w, barH = 14;
  const grad = ctx.createLinearGradient(x, y, x + barW, y);
  grad.addColorStop(0, "#1d4ed8");
  grad.addColorStop(0.33, "#16a34a");
  grad.addColorStop(0.66, "#ca8a04");
  grad.addColorStop(1, "#dc2626");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(x, y, barW, barH, 7) : ctx.rect(x, y, barW, barH);
  ctx.fill();
  y += barH + 8;

  ctx.fillStyle = "#9bb0cf";
  ctx.font = "500 11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Low (0.0)", x, y);
  ctx.textAlign = "center";
  ctx.fillText("Medium (0.5)", x + barW / 2, y);
  ctx.textAlign = "right";
  ctx.fillText("High (1.0)", x + barW, y);
  ctx.textAlign = "left";
  y += 22;

  // Stats summary
  const vals = ANALYSIS.map(a => adjustedValue(a[currentMode] || 0, currentMode));
  let avg = 0, mx = 0, mn = 0;
  if (vals.length) {{
    let sum = 0, mmx = -Infinity, mmn = Infinity;
    for (const v of vals) {{ sum += v; if (v > mmx) mmx = v; if (v < mmn) mmn = v; }}
    avg = sum / vals.length; mx = mmx; mn = mmn;
  }}
  ctx.fillStyle = "#cbe1ff";
  ctx.font = "600 14px 'JetBrains Mono', monospace";
  const statY = y;
  const statW = w / 3;
  ctx.fillText(avg.toFixed(2), x, statY);
  ctx.fillText(mx.toFixed(2), x + statW, statY);
  ctx.fillText(mn.toFixed(2), x + statW * 2, statY);
  ctx.fillStyle = "#8ea6c7";
  ctx.font = "500 10px Inter, sans-serif";
  ctx.fillText("AVERAGE", x, statY + 20);
  ctx.fillText("MAX", x + statW, statY + 20);
  ctx.fillText("MIN", x + statW * 2, statY + 20);
  return statY + 20 + 16;  // return next Y cursor
}}

function drawIndicatorBars(ctx, x, y, w, h) {{
  // Header
  ctx.fillStyle = "#86a3cc";
  ctx.font = "600 11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("INDICATOR AVERAGES (all modes)", x, y);
  y += 20;

  const avgs = computeIndicatorAverages();
  // Sort descending by value
  const sorted = INDICATOR_DIRECTIONS.slice().sort((a, b) => avgs[b.key] - avgs[a.key]);

  const rowH = 20;
  const labelW = 88;
  const valueW = 38;
  const barX = x + labelW;
  const barW = w - labelW - valueW - 4;

  for (const ind of sorted) {{
    const v = avgs[ind.key];
    // Label
    ctx.fillStyle = "#cbe1ff";
    ctx.font = "500 11px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(ind.label, x, y + rowH / 2);

    // Bar background
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(barX, y + 3, barW, rowH - 6, 4);
    else ctx.rect(barX, y + 3, barW, rowH - 6);
    ctx.fill();

    // Bar fill - color by direction
    let barColor;
    if (ind.direction === "bad") barColor = "#f97316";           // orange
    else if (ind.direction === "neutral") barColor = "#0ea5e9"; // blue
    else barColor = "#22c55e";                                   // green

    const fillW = Math.max(2, barW * Math.max(0, Math.min(1, v)));
    ctx.fillStyle = barColor;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(barX, y + 3, fillW, rowH - 6, 4);
    else ctx.rect(barX, y + 3, fillW, rowH - 6);
    ctx.fill();

    // Value
    ctx.fillStyle = "#e5eefc";
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "right";
    ctx.fillText(v.toFixed(2), x + w, y + rowH / 2);
    ctx.textAlign = "left";
    ctx.textBaseline = "top";

    y += rowH + 2;
  }}

  // Legend footnote for color meaning
  y += 4;
  ctx.font = "500 9px Inter, sans-serif";
  const spotY = y + 5;
  const drawDot = (cx, col) => {{
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(cx, spotY, 4, 0, Math.PI * 2);
    ctx.fill();
  }};
  drawDot(x + 4, "#22c55e");
  ctx.fillStyle = "#9bb0cf";
  ctx.fillText("high = good", x + 14, y + 1);
  drawDot(x + 86, "#0ea5e9");
  ctx.fillStyle = "#9bb0cf";
  ctx.fillText("neutral", x + 96, y + 1);
  drawDot(x + 146, "#f97316");
  ctx.fillStyle = "#9bb0cf";
  ctx.fillText("high = stress", x + 156, y + 1);

  return y + 18;
}}

function drawIndicatorRadar(ctx, x, y, w, h) {{
  // Header
  ctx.fillStyle = "#86a3cc";
  ctx.font = "600 11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText("INDICATOR PROFILE (solar inverted)", x, y);
  y += 18;

  // Compute values with solar flipped so all axes "higher = better"
  const avgs = computeIndicatorAverages();
  const axes = INDICATOR_DIRECTIONS.map(ind => {{
    let v = avgs[ind.key];
    let label = ind.label;
    if (ind.direction === "bad") {{
      v = 1 - v;
      label = ind.label + "⁻¹";  // superscript -1 to indicate inverted
    }}
    return {{ label: label, value: Math.max(0, Math.min(1, v)) }};
  }});

  const N = axes.length;
  const cx = x + w / 2;
  // Shift center up so bottom label has more room; reserve 36px at bottom for labels
  const cy = y + (h - 36) / 2;
  // Reserve 54px horizontal (both sides) and 30px vertical (each side) for labels
  const radius = Math.min(w / 2 - 54, (h - 36) / 2 - 20);

  // Draw concentric grid rings
  ctx.strokeStyle = "rgba(147,197,253,0.15)";
  ctx.lineWidth = 1;
  for (let r = 1; r <= 4; r++) {{
    const rr = radius * (r / 4);
    ctx.beginPath();
    for (let i = 0; i < N; i++) {{
      const a = -Math.PI / 2 + (i * 2 * Math.PI / N);
      const px = cx + Math.cos(a) * rr;
      const py = cy + Math.sin(a) * rr;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }}
    ctx.closePath();
    ctx.stroke();
  }}

  // Axis spokes
  ctx.strokeStyle = "rgba(147,197,253,0.18)";
  for (let i = 0; i < N; i++) {{
    const a = -Math.PI / 2 + (i * 2 * Math.PI / N);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius);
    ctx.stroke();
  }}

  // Data polygon
  ctx.beginPath();
  for (let i = 0; i < N; i++) {{
    const a = -Math.PI / 2 + (i * 2 * Math.PI / N);
    const rr = radius * axes[i].value;
    const px = cx + Math.cos(a) * rr;
    const py = cy + Math.sin(a) * rr;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }}
  ctx.closePath();
  ctx.fillStyle = "rgba(34,197,94,0.22)";
  ctx.fill();
  ctx.strokeStyle = "#22c55e";
  ctx.lineWidth = 2;
  ctx.stroke();

  // Data points
  for (let i = 0; i < N; i++) {{
    const a = -Math.PI / 2 + (i * 2 * Math.PI / N);
    const rr = radius * axes[i].value;
    const px = cx + Math.cos(a) * rr;
    const py = cy + Math.sin(a) * rr;
    ctx.fillStyle = "#22c55e";
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, Math.PI * 2);
    ctx.fill();
  }}

  // Axis labels (outside the chart) - smaller font, offset from radius
  ctx.fillStyle = "#cbe1ff";
  ctx.font = "500 9.5px Inter, sans-serif";
  const labelGap = 14;
  for (let i = 0; i < N; i++) {{
    const a = -Math.PI / 2 + (i * 2 * Math.PI / N);
    const lx = cx + Math.cos(a) * (radius + labelGap);
    const ly = cy + Math.sin(a) * (radius + labelGap);
    // Alignment based on position
    const cosA = Math.cos(a), sinA = Math.sin(a);
    if (Math.abs(cosA) < 0.25) ctx.textAlign = "center";
    else if (cosA > 0) ctx.textAlign = "left";
    else ctx.textAlign = "right";
    if (Math.abs(sinA) < 0.25) ctx.textBaseline = "middle";
    else if (sinA > 0) ctx.textBaseline = "top";
    else ctx.textBaseline = "bottom";
    ctx.fillText(axes[i].label, lx, ly);
  }}
  ctx.textAlign = "left";
  ctx.textBaseline = "top";

  return y + h;
}}

function drawFooter(ctx, W, H, padding) {{
  ctx.fillStyle = "#7f93b2";
  ctx.font = "500 11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  const now = new Date();
  const ds = now.toISOString().split("T")[0];
  ctx.fillText("VOX City Engine — Firman Afrianto & Maya Safira — " + ds, padding, H - padding);
  ctx.textAlign = "right";
  if (GEO_REF && GEO_REF.valid && GEO_REF.center) {{
    ctx.fillText("Center: " + GEO_REF.center[0].toFixed(4) + ", " + GEO_REF.center[1].toFixed(4),
      W - padding, H - padding);
  }}
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
}}

const TITLE_STRING = document.getElementById("title").innerText || "VOX City Engine";

function animate() {{
  requestAnimationFrame(animate);

  if (autoRotate) {{
    const t = Date.now() * 0.00015;
    const r = 600;
    camera.position.x = Math.cos(t) * r;
    camera.position.z = Math.sin(t) * r;
    camera.lookAt(0, 0, 0);
  }}

  controls.update();
  renderer.render(scene, camera);
}}
</script>
</body>
</html>"""