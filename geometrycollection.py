from shapely.geometry import Point, LineString
import pelog.logenv as logenv
from pelog.logenv import ObjectWithMultiProcess
from cfg.autonaviconvert_settings import CITY_IDS_PROC, OFFSET_DISTANCE
from dataparser.maptmcparser2 import MapTMCParser, MapDataPackagePoints, TmcOut
#plt.switch_backend('agg')
#from figures import SIZE
import pyproj
import cPickle as pickle
import os
#from sqlalchemy.sql.expression import false
wgs84=pyproj.Proj("+init=EPSG:4326")
mocato=pyproj.Proj("+init=EPSG:3857")


BLUE =   '#6699cc'
YELLOW = '#ffcc33'
GREEN =  '#339933'
GRAY =   '#999999'

CFG_PATH = './cfg'
cfg_path = CFG_PATH
logenv.init_logging_env(cfg_path)
logger = logenv.getLogger()
    
def split(line_string, line_string_b, faraway='none'):
    if not isinstance(line_string, LineString):
        return None
    if not isinstance(line_string_b, LineString):
        return None
    coords = line_string.coords
    if len(coords) < 2:
        return None
    j = None
    for i in range(len(coords) - 1):
        if LineString(coords[i:i + 2]).intersects(line_string_b):
            j = i
            break
    if j is None:
        return None
    intersect_point = LineString(coords[:j+2]).intersection(line_string_b)
    if not isinstance(intersect_point, Point):
        return None
    if intersect_point.is_empty:
        return None
    if (intersect_point.x, intersect_point.y) in [coords[0], coords[-1]]:
        return line_string
    if (intersect_point.x, intersect_point.y) == coords[j]:
        line_first = LineString(coords[:j+1])
        line_second = LineString(coords[j:])
    elif (intersect_point.x, intersect_point.y) == coords[j+1]:
        line_first = LineString(coords[:j+2])
        line_second = LineString(coords[j+1:])
    else:
        line_first = LineString(coords[:j+1] + [(intersect_point.x, intersect_point.y)])
        line_second = LineString([(intersect_point.x, intersect_point.y)] + coords[j+1:])
    
    if faraway == 'start':
        if line_second.length < 9.0: 
            return line_first
    elif faraway == 'end':
        if line_first.length < 9.0:
            return line_second
    else:
        if line_first.length < line_second.length and line_first.length < 9.0:
            return line_second
        if line_first.length >= line_second.length and line_second.length < 9.0: 
            return line_first    
    return None

def getExtrapoledLine(p1,p2):
    EXTRAPOL_RATIO = 4
    a = p1
    b = (p1[0]+EXTRAPOL_RATIO*(p2[0]-p1[0]), p1[1]+EXTRAPOL_RATIO*(p2[1]-p1[1]) )
    return LineString([a,b])

def extend_line(line, start_extend=True, end_extend=True, link_id=0):
    if not isinstance(line, LineString):
        return line
    startx = starty = endx = endy = 0
    output_line = line
    # end
    if end_extend:
        temp_line = LineString(line.coords[-2:])
        start_point = temp_line.coords[0]
        end_point = temp_line.coords[1]
        endx = start_point[0] + (end_point[0] - start_point[0]) * (temp_line.length + 4) / temp_line.length
        endy = start_point[1] + (end_point[1] - start_point[1]) * (temp_line.length + 4) / temp_line.length
    # start
    if start_extend:
        temp_line = LineString([line.coords[1], line.coords[0]])
        start_point = temp_line.coords[0]
        end_point = temp_line.coords[1]
        if temp_line.length == 0:
            tileid = (link_id>>32) & 0xFFFFFFFF
            linkid = link_id & 0xFFFFFFFF
            print tileid, linkid
            temp_line = LineString([line.coords[2], line.coords[0]])
            start_point = temp_line.coords[0]
            end_point = temp_line.coords[1]
            
        startx = start_point[0] + (end_point[0] - start_point[0]) * (temp_line.length + 4) / temp_line.length
        starty = start_point[1] + (end_point[1] - start_point[1]) * (temp_line.length + 4) / temp_line.length
    if start_extend and end_extend:
        output_line = LineString([(startx, starty)] + line.coords[:] + [(endx, endy)])
    elif start_extend:
        output_line = LineString([(startx, starty)] + line.coords[:])
    elif end_extend:
        output_line = LineString(line.coords[:] + [(endx, endy)])
    return output_line        

def cut_line_at_points(line, point):
    # First coords of line (start + end)
    coords = [line.coords[0], line.coords[-1]]
    # Add the coords from the points
    coords += [list(point.coords)[0]]
    # Calculate the distance along the line for each point
    dists = [line.project(Point(p)) for p in coords]
    # sort the coords based on the distances
    # see http://stackoverflow.com/questions/6618515/sorting-list-based-on-values-from-another-list
    coords = [p for (d, p) in sorted(zip(dists, coords))]
    # generate the Lines
    lines = [LineString([coords[i], coords[i+1]]) for i in range(len(coords)-1)]
    return lines

def offset(logic_layer, line_string, side):
    try:
        line_temp = line_string.parallel_offset(distance=OFFSET_DISTANCE[logic_layer], side=side, join_style=1)
        return line_temp
    except:
        return None
    
def plot_coords(ax, ob):
    x, y = ob.xy
    ax.plot(x, y, 'o', color=GRAY, zorder=1)

def plot_line(ax, ob, alpha=1.0, linewidth=1, color=GRAY):
    parts = hasattr(ob, 'geoms') and ob or [ob]
    for part in parts:
        if hasattr(part,'xy'):
            x, y = part.xy
            ax.plot(x, y, color=color, linewidth=linewidth, alpha=alpha, solid_capstyle='round', zorder=1)
        else:
            logger.info("type=%s" % (type(part)))
            
def offset_line_cut(inter_link, link_left, link_right):
    if not isinstance(inter_link, LineString):
        return None
    split_line = inter_link
    if not isinstance(link_left, LineString) and not isinstance(link_right, LineString):
        return None
    elif not isinstance(link_left, LineString):
        is_crosses = split_line.intersects(link_right)
        if is_crosses:
            link_temp = split(split_line, link_right)
            if link_temp:
                split_line = link_temp
        return split_line
    elif not isinstance(link_right, LineString):
        is_crosses = split_line.intersects(link_left)
        if is_crosses:
            link_temp = split(split_line, link_left)
            if link_temp:
                split_line = link_temp
        return split_line
    coords = split_line.coords
    if len(coords) < 2:
        return None
    centroid_left = Point(link_left.coords[0])
    centroid_right = Point(link_right.coords[0])
    start_point = Point(coords[0])
    end_point = Point(coords[-1])
    start_distance = start_point.distance(centroid_left) + start_point.distance(centroid_right)
    end_distance = end_point.distance(centroid_left) + end_point.distance(centroid_right)
    faraway_point = 'start'
    if start_distance < end_distance:
        faraway_point = 'end'
    is_crosses = split_line.intersects(link_left)
    if is_crosses:
        link_temp = split(split_line, link_left, faraway=faraway_point)
        if link_temp:
            split_line = link_temp
    is_crosses = split_line.intersects(link_right)
    if is_crosses:
        link_temp = split(split_line, link_right, faraway=faraway_point)
        if link_temp:
            split_line = link_temp
    return split_line

def cut_line(dict_link_string, dict_intersect):
    dict_link_output = {}
    for (link_id, list_link_string) in dict_link_string.items():
        # if oneway != 1
        if len(list_link_string) == 1:
            dict_link_output[link_id] = list_link_string
            continue
        inter_links = dict_intersect.get(link_id, None)
        if not inter_links:
            continue
        dict_link_output[link_id] = []
        for link_string in list_link_string:
            split_line = link_string
            for inter_link in inter_links:
                list_inter_string = dict_link_string.get(inter_link, None)
                if not list_inter_string:
                    continue
#                 if len(list_inter_string) == 2:
#                     link_temp = offset_line_cut(split_line, list_inter_string[0], list_inter_string[1])
#                     if link_temp:
#                         split_line = link_temp
#                     continue
                for inter_string in list_inter_string:
                    is_crosses = split_line.intersects(inter_string)
                    if is_crosses:
                        link_temp = split(split_line, inter_string)
                        if link_temp:
                            split_line = link_temp
            dict_link_output[link_id].append(split_line)
    return dict_link_output
           
def extend_lines(list_line_offset):
    list_line_output = []
    for line_offset in list_line_offset:
        split_line = extend_line(line_offset)
        list_line_output.append(split_line)      
    return list_line_output
    
def process_offset(logic_layer, dict_node, dict_tile_link, dict_intersect):
    dict_link_string = {}
    # extend lines
    for (_, source_link) in dict_tile_link.items():
        link_id = source_link.map_tile_link_id
        oneway = source_link.map_link_oneway
        if oneway == 1:
            start_point = source_link.points[0]
            end_point = source_link.points[-1]
            link_list = dict_node.get((start_point.x, start_point.y))
            extend_start = False
            extend_end = False
            if len(link_list) == 2:
                extend_start = True
            link_list = dict_node.get((end_point.x, end_point.y))
            if len(link_list) == 2:
                extend_end = True
            lonlat_list = []
            for i in range(len(source_link.points)):
                #logger.info("points=%s" % ','.join(v42.points[i].x/500000.0, v42.points[i].y/500000.0))
                lonlat_list.append(pyproj.transform(wgs84,mocato,source_link.points[i].x/500000.0, source_link.points[i].y/500000.0))
                #lonlat_list.append((v42.points[i].x/500000.0, v42.points[i].y/500000.0))
            line_temp = LineString(lonlat_list)
            line_extend = extend_line(line_temp, extend_start, extend_end, link_id)
            if isinstance(line_extend, LineString) and not line_extend.is_empty and len(line_extend.coords) >= 2:
                dict_link_string[link_id] = [offset(logic_layer, line_extend, 'left')]
                link_temp = offset(logic_layer, line_extend, 'right')
                if isinstance(link_temp, LineString):
                    link_temp = LineString(list(link_temp.coords)[::-1])
                    dict_link_string[link_id].append(link_temp)
        else:
            lonlat_list = []
            for i in range(len(source_link.points)):
                #logger.info("points=%s" % ','.join(v42.points[i].x/500000.0, v42.points[i].y/500000.0))
                lonlat_list.append(pyproj.transform(wgs84,mocato,source_link.points[i].x/500000.0, source_link.points[i].y/500000.0))
                #lonlat_list.append((v42.points[i].x/500000.0, v42.points[i].y/500000.0))
            line_temp = LineString(lonlat_list)
            dict_link_string[link_id] = [line_temp]
            
    # offset and cut
    dict_link_output = cut_line(dict_link_string, dict_intersect)
    return dict_link_output
    
        
if __name__ == '__main__':
    #fig = plt.figure(1, figsize=(10,4), dpi=300) #1, figsize=(10, 4), dpi=180)
#     a = LineString([(0, 0), (2, 2)])
#     b = LineString([(1.0, 0.0), (1.0,1.5)])
#     d = split(b,a)
    
    test = MapTMCParser()
    data_path = '/mnt/traffic_data/city_tmc1'
    for files in os.listdir(data_path):
        newDir = os.path.join(data_path, files)
        if not os.path.isfile(newDir):
            continue
        test = MapTMCParser()
        if not test.ParseSingleCityData(newDir):
            continue
    
        # {city_code: MapCityData()}
        # MapCityData().data_pack_dict{physical_layer_id: {super_tile_id: SuperTileData()}}
        for (k1, v1) in test.city_raw2map_link_dict.items():
            logger.info("city_code=%s" % (k1))
            logger.info("file_header=%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" %
                        (v1.file_header.file_flag,
                        v1.file_header.header_size,
                        v1.file_header.rawdata_ver,
                        v1.file_header.compile_ver,
                        v1.file_header.provider_code ,
                        v1.file_header.data_proj_code,
                        v1.file_header.map_inspect_no,
                        v1.file_header.map_publish_no,
                        v1.file_header.map_copy_right,
                        v1.file_header.city_code))
            for (k2, v2) in v1.data_pack_dict.items():
                logger.info("physical_layer_id=%s" % (k2))
                for (k3, v3) in v2.items():
                    #logger.info("super_tile_id=%s" % (k3))
    #                 for (k41, v41) in v3.raw2map_table_dict.items():
    #                     logger.info("rawlinkid=%s" % (k41))
                    #
                    # todo 3 DICT
                    dict_node = {}
                    dict_tile_link = {}
                    dict_intersect = {}
                    for (k42, v42) in v3.map_link_table_dict.items():
                        #logger.info("maptileid_linkid=%s" % (k42))
                        #logger.info("oneway=%s" % (v42.map_link_oneway))
                        link_id = v42.map_tile_link_id
                        dict_tile_link[link_id] = v42
                        dict_intersect[link_id] = []
                        for i in range(len(v42.points)):
                            find_links = dict_node.get((v42.points[i].x, v42.points[i].y), None)
                            if find_links:
                                for find_link in find_links:
                                    inter_links = dict_intersect.get(find_link, None)
                                    if inter_links is not None:
                                        inter_links.append(link_id)
                                    dict_intersect[link_id].append(find_link)
                                find_links.append(link_id)
                            else:
                                dict_node[(v42.points[i].x, v42.points[i].y)] = [link_id]
                    dict_link_output = process_offset(k2, dict_node, dict_tile_link, dict_intersect)
                    for (k42, v42) in v3.map_link_table_dict.items():
                        link_id = v42.map_tile_link_id
                        link_oneway = v42.map_link_oneway
                        if link_oneway == 2:
                            temp_points = v42.points
                            v42.points = []
                            v42.points.append(temp_points)
                            v42.points.append([])
                        elif link_oneway == 3:
                            temp_points = v42.points
                            v42.points = []
                            v42.points.append([])
                            v42.points.append(temp_points)
                        else:
                            v42.points = []
                            list_link_string = dict_link_output.get(link_id, [])
                            if len(list_link_string) == 1:
                                if isinstance(list_link_string[0], LineString):
                                    points_list = []
                                    for point_index in range(len(list_link_string[0].coords)):
                                        x,y = pyproj.transform(mocato,wgs84,\
                                            list_link_string[0].coords[point_index][0], list_link_string[0].coords[point_index][1])
                                        package_points = MapDataPackagePoints()
                                        package_points.x = int(x*500000.0)
                                        package_points.y = int(y*500000.0)
                                        points_list.append(package_points)
                                    v42.points.append(points_list)
                                else:
                                    v42.points.append([])
                                v42.points.append([])
                            elif len(list_link_string) == 2:
                                if isinstance(list_link_string[0], LineString):
                                    points_list = []
                                    for point_index in range(len(list_link_string[0].coords)):
                                        x,y = pyproj.transform(mocato,wgs84,\
                                            list_link_string[0].coords[point_index][0], list_link_string[0].coords[point_index][1])
                                        package_points = MapDataPackagePoints()
                                        package_points.x = int(x*500000.0)
                                        package_points.y = int(y*500000.0)
                                        points_list.append(package_points)
                                    v42.points.append(points_list)
                                else:
                                    v42.points.append([])
                                if isinstance(list_link_string[1], LineString):
                                    points_list = []
                                    for point_index in range(len(list_link_string[1].coords)):
                                        x,y = pyproj.transform(mocato,wgs84,\
                                            list_link_string[1].coords[point_index][0], list_link_string[1].coords[point_index][1])
                                        package_points = MapDataPackagePoints()
                                        package_points.x = int(x*500000.0)
                                        package_points.y = int(y*500000.0)
                                        points_list.append(package_points)
                                    v42.points.append(points_list)
                                else:
                                    v42.points.append([])
                            else:
                                v42.points.append([])
                                v42.points.append([])
                    del dict_node
                    del dict_tile_link
                    del dict_intersect
                    del dict_link_output
            # save file
            output_file = '/mnt/traffic/output1/' + str(k1) + '_' + str(v1.file_header.compile_ver) + '.pkl'
            #output_file = open(output_file, 'wb')
            #pickle.dump(v1.data_pack_dict, output_file, -1)
            #output_file.close()
            out = TmcOut(v1, output_file)
            out.save()
   
    
    logger.info("calc end!")
    # plot line
#     from matplotlib import pyplot as plt
#     fig = plt.figure(dpi=150)
#     fig.set_size_inches(120,120)
#     # 1: disconnected multilinestring
#     ax = fig.add_subplot(111)
#     xmin = ymin = 1e10
#     xmax = ymax = -1e10
#     for (link_id, list_link_string) in dict_link_output.items():
#         if len(list_link_string) == 1:
#             minx1,miny1,maxx2,maxy2 = list_link_string[0].bounds
#             if minx1 < xmin:
#                 xmin = minx1
#             if miny1 < ymin:
#                 ymin = miny1
#             if maxx2 > xmax:
#                 xmax = maxx2
#             if maxy2 > ymax:
#                 ymax = maxy2
#             plot_line(ax, list_link_string[0], color=GRAY, alpha=0.8)
#         else:
#             for link_string in list_link_string:
#                 minx1,miny1,maxx2,maxy2 = link_string.bounds
#                 if minx1 < xmin:
#                     xmin = minx1
#                 if miny1 < ymin:
#                     ymin = miny1
#                 if maxx2 > xmax:
#                     xmax = maxx2
#                 if maxy2 > ymax:
#                     ymax = maxy2
#                 plot_line(ax, link_string, color=GREEN)
#     
#     
#     ax.set_title('a) lines')
#     
#     xrange = [xmin, xmax]
#     yrange = [ymin, ymax]
#     ax.set_xlim(*xrange)
#     #ax.set_xticks(range(*xrange) + [xrange[-1]])
#     ax.set_ylim(*yrange)
#     #ax.set_yticks(range(*yrange) + [yrange[-1]])
#     #ax.set_aspect(1)
#     
#     fig.savefig('/home/ubuntu/Documents/test.svg', format='svg')
#     fig.clf()
    #plt.close()
    #plt.show()

