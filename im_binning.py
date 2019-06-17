from baseline import *

import time
from operator import itemgetter

def get_points(spec):
    """Data preprocessing to extract the retention time, mass to charge, intensity,
    and ion mobility for each peak in a spectrum.

    Args:
        spec (MSSpectrum): An OpenMS MSSpectrum object.

    Returns:
        list<list<double, double, double, double>>: A list of lists, where each
        interior list holds RT, MZ, intensity, and IM information (in that order)
        for a single peak in the spectrum. The exterior list is unsorted.
    """
    point_data = zip(*spec.get_peaks(), spec.getFloatDataArrays()[0])
    return [[spec.getRT(), mz, intensity, im] for mz, intensity, im in point_data]

def run(args):
    """Collects all points from all spectra.
    """
    exp = ms.MSExperiment()
    ms.MzMLFile().load(args.infile + '.mzML', exp)
    print("Raw data file loaded; beginning execution")

    # Store the RT, MZ, intensity, and IM data for every peak in every spectrum
    point_cloud = []

    spectra = exp.getSpectra()
    for i in range(args.num_frames):
        spec = spectra[i]

        new_points = get_points(spec)
        point_cloud.extend(new_points)

    print("Sorting data points")
    # Sort points by IM ascending (using lambda significantly slower)
    start = time.time()
    #sorted_cloud = sorted(point_cloud, key=lambda x: x[3])
    sorted_cloud = sorted(point_cloud, key=itemgetter(3))
    end = time.time()
    print("Number of data points:", len(sorted_cloud))
    print("Time to sort:", end - start)

def run_ff(exp, type):
    """Runs a feature finder on the given input map.

    Args:
        exp (MSExperiment): An OpenMS MSExperiment object.
        type (string): The name of the feature finder to run.

    Returns:
        FeatureMap: Contains the found features from the given experiment.
    """
    ff = ms.FeatureFinder()
    ff.setLogType(ms.LogType.CMD)

    features = ms.FeatureMap()
    seeds = ms.FeatureMap()
    params = ms.FeatureFinder().getParameters(type)

    # Parameters for FeatureFinderCentroided
    params.__setitem__(b'mass_trace:min_spectra', 5)
    params.__setitem__(b'mass_trace:max_missing', 2)
    params.__setitem__(b'seed:min_score', 0.5)
    params.__setitem__(b'feature:min_score', 0.5)
    
    exp.updateRanges()
    ff.run(type, exp, features, params, seeds)

    features.setUniqueIds()
    return features

def find_features(spec, outdir, outfile, spec_idx=0):
    """Make one pass at binning a spectrum and finding its features.

    Args:
        spec (MSSpectrum): An OpenMS MSSpectrum object.
        outdir (string): The output directory for FeatureXML files.
        outfile (string): A string to identify this series of runs.
        spec_idx (int): The index of this spectrum in a series of spectra.
    """
    points = get_points(spec)
    # Sort points by IM ascending
    sorted_points = sorted(points, key=itemgetter(3))

    # Position of bin i (0-indexed) = i * bin_size + first_im
    first_im, last_im = sorted_points[0][3], sorted_points[len(points) - 1][3]
    delta_im, offset_im = last_im - first_im, 0
    
    num_bins = 50
    bin_size = delta_im / num_bins
    # For successive passes, use offset_im to shift bins
    offset_delta, pass_num = 0.05, 1

    bins, new_exp = [], []
    for i in range(num_bins):
        bins.append([])
        new_exp.append(ms.MSExperiment())

    # Step 1: assign points to bins
    for i in range(len(points)):
        # Need to adapt this formula for offset_im
        bin_idx = int((sorted_points[i][3] - first_im) / bin_size)
        if bin_idx >= num_bins:
            bin_idx = num_bins - 1
        bins[bin_idx].append(sorted_points[i])

    # Step 2: for each m/z, average the intensities
    for i in range(num_bins):
        bins[i] = sorted(bins[i], key=itemgetter(1))
        mz_start, num_mz, curr_mz = 0, 0, bins[i][0][1]
        run_intensity = 0

        for j in range(len(bins[i])):
            if (bins[i][j][1] == curr_mz):
                num_mz += 1
                run_intensity += bins[i][j][2]
            else:
                # Reached a new m/z slice; update the previous intensities
                run_intensity /= num_mz
                for k in range(mz_start, mz_start + num_mz):
                    bins[i][k][2] = run_intensity

                mz_start, num_mz, curr_mz = j, 1, bins[i][j][1]
                run_intensity = bins[i][j][2]

        # Takes care of the last slice (if required)
        if num_mz > 0:
            run_intensity /= num_mz
            for k in range(mz_start, mz_start + num_mz):
                bins[i][k][2] = run_intensity

        # Get the arrays of RT, MZ, Intensity, and IM
        transpose = list(zip(*bins[i]))

        new_spec = ms.MSSpectrum()
        new_spec.setRT(spec.getRT())
        new_spec.set_peaks((list(transpose[1]), list(transpose[2])))

        fda = ms.FloatDataArray()
        for j in list(transpose[3]):
            fda.push_back(j)
        new_spec.setFloatDataArrays([fda])

        new_exp[i].addSpectrum(new_spec)
        ms.MzMLFile().store(outdir + '/' + outfile + '-spec' + str(spec_idx) + '-pass' +
                            str(pass_num) + '-bin' + str(i) + '.mzML', new_exp[i])

    # Step 3: find the features for each bin
    ff_type = 'centroided'
    for i in range(num_bins):
        features = run_ff(new_exp[i], ff_type)
        ms.FeatureXMLFile().store(outdir + '/' + outfile + '-spec' + str(spec_idx) +
                                  '-pass' + str(pass_num) + '-bin' + str(i) +
                                  '.featureXML', features)

if __name__ == "__main__":
    # Includes legacy arguments from baseline.py
    parser = argparse.ArgumentParser(description='4D LC-IMS/MS Feature Finder')
    parser.add_argument('--infile', action='store', required=True, type=str)
    parser.add_argument('--outfile', action='store', required=True, type=str)
    parser.add_argument('--outdir', action='store', required=True, type=str)
    parser.add_argument('--mz_epsilon', action='store', required=False, type=float)
    parser.add_argument('--im_epsilon', action='store', required=False, type=float)
    parser.add_argument('--num_frames', action='store', required=False, type=int)
    parser.add_argument('--window_size', action='store', required=False, type=int)
    parser.add_argument('--rt_length', action='store', required=False, type=int)

    args = parser.parse_args()

    exp = ms.MSExperiment()
    print('Loading mzML input file')
    ms.MzMLFile().load(args.infile + '.mzML', exp)
    print('mzML input file loaded')

    spectra = exp.getSpectra()
    for i in range(args.num_frames):
        spec = spectra[i]
        find_features(spec, args.outdir, args.outfile, i)
