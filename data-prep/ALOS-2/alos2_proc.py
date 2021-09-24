#!/usr/bin/env python

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import rasterio
import geopandas as gpd


layer_suffix = {
    'HH': 'sl_HH',
    'HV': 'sl_HV',
    'INC': 'linci',
    'DOY': 'date',
}


def build_vrt(year, src):
    yy = str(year)[2:]
    if year < 2014:
        # ALOS
        postfix = ''
        launch_date = date(2006, 1, 24)
    else:
        # ALOS-2
        postfix = 'F02DAR'
        launch_date = date(2014, 5, 24)

    tarfile_pattern = re.compile(r'^[N|S]{1}\w{2}[E|W]{1}\w{3}_\w{2}_MOS')

    # The .tar.gz files should be under src/year/tarfiles
    ls_cmd = f'ls {src}/*.tar.gz'
    if isinstance(src, str):
        ls_cmd = 'gsutil ' + ls_cmd
    tarfile_list = [Path(p).name for p in subprocess.check_output(ls_cmd, shell=True).decode(sys.stdout.encoding).splitlines()]
    for tarfile in tarfile_list:
        if not tarfile_pattern.match(tarfile):
            tarfile_list.remove(tarfile)
    if not tarfile_list:
        raise Exception(f'No .tar.gz files found under {src}/{year}/tarfiles/.')

    if year < 2019:
        suffix = ''
    else:
        suffix = '.tif'

    for layer in ['HH', 'HV', 'INC', 'DOY']:
        vrt_0 = Path(f'{layer}_0.vrt')
        tif_list = []
        for tarfile in tarfile_list:
            tile = tarfile.split('_')[0]
            if isinstance(src, Path):
                tif = f'/vsitar/{src}/{tarfile}/{tile}_{yy}_{layer_suffix[layer]}_{postfix}{suffix}'
            elif isinstance(src, str):
                u = urlparse(src)
                bucket = u.netloc
                prefix = u.path.strip('/')
                tif = f'/vsitar/vsis3/{bucket}/{prefix}/{tarfile}/{tile}_{yy}_{layer_suffix[layer]}_{postfix}{suffix}'
            tif_list.append(tif)
        cmd = f'gdalbuildvrt -overwrite {vrt_0} {" ".join(tif_list)}'
        subprocess.check_call(cmd, shell=True)

        # Convert HH/HV/INC to Float32, DOY to Int16
        vrt_1 = Path(f'{layer}_1.vrt')
        if layer in ['HH', 'HV', 'INC']:
            cmd = f'gdal_translate -ot Float32 {vrt_0} {vrt_1}'
        else:
            cmd = f'gdal_translate -ot Int16 {vrt_0} {vrt_1}'


def warp_to_tiles(utm_tiles):

    gdf = gpd.read_file(utm_tiles)

    # t_res = 30
    # t_epsg = gdf.crs.to_epsg()

    # for i in gdf.index:
    #     h = gdf['h'][i]
    #     v = gdf['v'][i]
    #     m = gdf['mask'][i]
    #     p = gdf['geometry'][i]

    #     for var in ['DOY', 'HH', 'HV', 'INC']:
    #         vrt = f'{var}.vrt'
    #         out_tif = f'/vsis3/{bucket}/{prefix}/alos2_mosaic_{state}_{year}_h{h}v{v}_{var}.tif'

    #         xmin = p.bounds[0]
    #         ymin = p.bounds[1]
    #         xmax = p.bounds[2]
    #         ymax = p.bounds[3]

    #         if var in ['HH', 'HV', 'INC']:
    #             wt = 'Float32'
    #             ot = 'Float32'
    #             nodata = 'nan'
    #             resampling = 'bilinear'
    #         else:
    #             wt = 'Int16'
    #             ot = 'Int16'
    #             nodata = 0
    #             resampling = 'near'

    #         cmd = (f'gdalwarp -overwrite '
    #             f'-t_srs EPSG:{t_epsg} -et 0 '
    #             f'-te {xmin} {ymin} {xmax} {ymax} '
    #             f'-tr {t_res} {t_res} '
    #             f'-wt {wt} -ot {ot} '
    #             f'-dstnodata {nodata} '
    #             f'-r {resampling} '
    #             f'-co COMPRESS=LZW '
    #             f'--config CPL_VSIL_USE_TEMP_FILE_FOR_RANDOM_WRITE YES '
    #             f'{vrt} {out_tif}')
    #         subprocess.check_call(cmd, shell=True)

            # if var == 'DOY':
            #     with rasterio.open(out_tif, 'r+') as dset:
            #         days_after_launch = dset.read(1)
            #         mask = dset.read_masks(1)
            #         doy = days_after_launch + (launch_date - date(year, 1, 1)).days + 1
            #         doy[mask == 0] = dset.nodata
            #         dset.write(doy, 1)

def main():
    parser = argparse.ArgumentParser(
        description='download ALOS/ALOS-2 Mosaic data from JAXA website'
    )
    parser.add_argument('tiles', metavar='tiles',
                        type=str,
                        help='geojson of UTM tiles generated by prep_tiles.py')
    parser.add_argument('year', metavar='year',
                        type=int,
                        help=('year'))
    parser.add_argument('src', metavar='src',
                        type=str,
                        help=('source location (s3:// or gs:// or local paths); '
                              'downloaded ALOS/ALOS-2 Mosaic data expected to be found under src/year/tarfiles/'))
    parser.add_argument('dst', metavar='dst',
                        type=str,
                        help=('destination location (s3:// or gs:// or local paths); '
                              'processed data will be stored under dst/year/'))
    args = parser.parse_args()

    # Check src
    u = urlparse(args.src)
    if u.scheme == 's3' or u.scheme == 'gs':
        srcloc = u.scheme
        bucket = u.netloc
        prefix = u.path.strip('/')
        src = f'{srcloc}://{bucket}/{prefix}/{args.year}/tarfiles'
        subprocess.check_call(f'gsutil ls {src}',
                              stdout=subprocess.DEVNULL,
                              shell=True)
    else:
        srcloc = 'local'
        src = Path(args.src) / f'{args.year}/tarfiles'
        if not src.is_dir():
            raise Exception(f'{args.src} is not a valid directory path')

    # Check dst
    u = urlparse(args.dst)
    if u.scheme == 's3' or u.scheme == 'gs':
        dstloc = u.scheme
        bucket = u.netloc
        prefix = u.path.strip('/')
        dst = f'{dstloc}://{bucket}/{prefix}/{args.year}'
        subprocess.check_call(f'gsutil ls {dst}',
                              stdout=subprocess.DEVNULL,
                              shell=True)
    else:
        dstloc = 'local'
        dst = Path(args.dst) / f'{args.year}'
        if not dst.is_dir():
            raise Exception(f'{args.dst} is not a valid directory path')

    build_vrt(args.year, src)



if __name__ == '__main__':
    main()