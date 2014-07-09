#!/usr/bin/env python
# geotecha - A software suite for geotechncial engineering
# Copyright (C) 2013  Rohan T. Walker (rtrwalker@gmail.com)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see http://www.gnu.org/licenses/gpl.html.

"""
Speccon 1d with stone column
"""
from __future__ import division, print_function
import geotecha.piecewise.piecewise_linear_1d as pwise
from geotecha.piecewise.piecewise_linear_1d import PolyLine
import geotecha.speccon.integrals as integ
import geotecha.math.transformations as transformations




import itertools

import geotecha.inputoutput.inputoutput as inputoutput

import geotecha.speccon.speccon1d as speccon1d

import geotecha.plotting.one_d #import MarkersDashesColors as MarkersDashesColors
import time
import sys
import textwrap
import numpy as np
import matplotlib
import matplotlib.pyplot as plt


from geotecha.inputoutput.inputoutput import GenericInputFileArgParser
try:
    #for python 2 to 3 stuff see http://python3porting.com/stdlib.html
    #for using BytesIO instead of StringIO see http://stackoverflow.com/a/3423935/2530083
    from io import BytesIO as StringIO
except ImportError:
    from StringIO import StringIO



class Speccon1dVRC(speccon1d.Speccon1d):
    """


    1d consolidation with:

    - vertical and radial drainage (radial drainage uses the eta method)
    - material properties that are constant in time but piecewsie linear with
      depth

      - vertical permeability
      - horizontal permeability
      - lumped drain parameter eta
      - lumped soil/column volume compressibilty (mv)

    - surcharge

      - distribution with depth does not change over time
      - magnitude varies piecewise linear with time
      - multiple loads can be superposed

    - pore pressure boundary conditions at top and bottom vary piecewise
      linear with time
    - calculates

      - excess pore pressure at depth (in soil and drain)
      - average excess pore pressure between depths
      - settlement between depths

    Parameters
    ----------
    reader : object that can be run with exec to produce a module
        reader can be for examplestring, fileobject, StringIO.`reader`
        should contain a statements such as H = 1, drn=0 corresponding to the
        input attributes listed below.  The user should pick an appropriate
        combination of attributes for their analysis.  e.g. don't put dTh=,
        kh=, et=, if you are not modelling radial drainage.  You do not have to
        initialize with `reader` but you should know what you are doing.

    Attributes
    ----------
    H : float, optional
        total height of soil profile. default = 1.0. Note that even though
        this program deals with normalised depth values it is important to
        enter the correct H value.  As it is used when plotting, outputing
        data and in normalising gradient boundary conditions (see
        `bot_vs_time` below) and pumping velocities (see `pumping` below).
    mvref : float, optional
        reference value of volume compressibility mv (used with `H` in
        settlement calculations). default = 1.0.  Note mvref will be used to
        normalise pumping velocities (see `pumping` below).
    kvref : float, optional
        reference value of vertical permeability kv  in soil (only used for pretty
        output). default = 1.0
    kvcref : float, optional
        reference value of vertical permeability kvc in column (only used for pretty
        output). default = 1.0
    khref : float, optional
        reference value of horizontal permeability kh in soil (only used for
        pretty output). default = 1.0
    khcref : float, optional
        reference value of horizontal permeability khc in column (only used for
        pretty output). default = 1.0
    etref : float, optional
        reference value of lumped drain parameter et (only used for pretty
        output). default = 1.0
    drn : {0, 1}, optional
        drainage boundary condition. default = 0
        0 = Pervious top pervious bottom (PTPB)
        1 = Pervious top impoervious bottom (PTIB)
    n : float
        ratio of influence radius to column radius, n=re/rc. (needed for
        alpha=1/n**2).
    dT : float, optional
        convienient normaliser for time factor multiplier. default = 1.0
    neig: int, optional
        number of series terms to use in solution. default = 2
    dTv: float, optional
        vertical reference time factor multiplier.  dTv is calculated with
        the chosen reference values of kv and mv: dTv = kv /(mv*gamw) / H ^ 2
    dTvc: float, optional
        well reference vertical time factor multiplier.  dTvc is calculated with
        the chosen reference values of kvc and mv:
        dTw = kvc /(mv*gamw) / H ^ 2.
    dTh : float, optional
        horizontal reference time factor multiplier.  dTh is calculated with
        the reference values of kh, et, and mv: dTh = kh / (mv * gamw) * et
    dThc : float, optional
        horizontal reference time factor multiplier.  dTh is calculated with
        the reference values of khc, and mv: dThc = 8*khc / (mv * gamw) /rc**2

    mv : PolyLine
        normalised volume compressibility PolyLine(depth, mv).  The mv here
        is the value of ms / (1 + alp * (Y - 1)) normalised by mvref.  Y is
        column to soil stiffness ratio ms/mc or Ec/Es
    kh : PolyLine, optional
        normalised horizontal permeability PolyLine(depth, kh)
    khc : PolyLine, optional
        normalised horizontal permeability in column PolyLine(depth, khc)
    kv : PolyLine , optional
        normalised vertical permeability PolyLine(depth, kv)
    kvc : PolyLine , optional
        normalised vertical permeability in column PolyLine(depth, kvc)
    et : PolyLine, optional
        normalised vertical drain parameter PolyLine(depth, et).
        et = 2 / (mu * re^2) where mu is smear-zone/geometry parameter and re
        is radius of influence of vertical drain
    surcharge_vs_depth : list of Polyline, optional
        surcharge variation with depth. PolyLine(depth, multiplier)
    surcharge_vs_time : list of Polyline, optional
        surcharge magnitude variation with time. PolyLine(time, magnitude)
    surcharge_omega_phase : list of 2 element tuples, optional
        (omega, phase) to define cyclic variation of surcharve. i.e.
        mag_vs_time * cos(omega*t + phase). if surcharge_omega_phase is None
        then cyclic componenet will be ignored.  if surcharge_omega_phase is a
        list then if any member is None then cyclic component will not be
        applied for that load combo.
    top_vs_time : list of Polyline, optional
        top p.press variation with time. Polyline(time, magnitude)
    top_omega_phase : list of 2 element tuples, optional
        (omega, phase) to define cyclic variation of top BC. i.e.
        mag_vs_time * cos(omega*t + phase). if top_omega_phase is None
        then cyclic componenet will be ignored.  if top_omega_phase is a
        list then if any member is None then cyclic component will not be
        applied for that load combo.
    bot_vs_time : list of Polyline, optional
        bottom p.press variation with time. Polyline(time, magnitude).
        When drn=1, i.e. PTIB, bot_vs_time is equivilent to saying
        D[u(H,t), z] = bot_vs_time. Within the program the actual gradient
        will be normalised with depth by multiplying H.
    bot_omega_phase : list of 2 element tuples, optional
        (omega, phase) to define cyclic variation of bot BC. i.e.
        mag_vs_time * cos(omega*t + phase). if bot_omega_phase is None
        then cyclic componenet will be ignored.  if bot_omega_phase is a
        list then if any member is None then cyclic component will not be
        applied for that load combo.
    fixed_ppress: list of 3 element tuple, optional
        (zfixed, pseudo_k, PolyLine(time, magnitude)).  zfixed is the
        normalised z at which pore pressure is fixed. pseudo_k is a
        permeability-like coefficient that controls how quickly the pore
        pressure reduces to the fixed value (pseudo_k should be as high as
        possible without causing numerical difficulties). If the third
        element of the tuple is None then the pore pressure will be fixed at
        zero rather than a prescribed mag_vs_time PolyLine.
    fixed_ppress_omega_phase : list of 2 element tuples, optional
        (omega, phase) to define cyclic variation of fixed ppress. i.e.
        mag_vs_time * cos(omega*t + phase). if fixed_ppress _omega_phase is
        None then cyclic componenet will be ignored.  if
        fixed_ppress_omega_phase is a list then if any member is None then
        cyclic component will not be applied for that load combo.
    pumping: list of 2 element tuple
        (zpump, mag_vs_time).  `zpump` is the normalised
        z at which pumping takes place. The mag_vs_time polyline should be
        the actual pumping velocity.  Within the program the actual pumping
        velocity will be normalised by dividing by (mvref * H).
        Negative values of vp will pump fluid out of the model, positive
        values of vp will pump fluid into the model.
    pumping_omega_phase : list of 2 element tuples, optional
        (omega, phase) to define cyclic variation of pumping velocity. i.e.
        mag_vs_time * cos(omega*t + phase). if pumping_omega_phase is
        None then cyclic componenet will be ignored.  if pumping_omega_phase is
        a list then if any member is None then cyclic component will not be
        applied for that load combo.
    ppress_z : list_like of float, optional
        normalised z to calc pore pressure at
    avg_ppress_z_pairs : list of two element list of float, optional
        nomalised zs to calc average pore pressure between
        e.g. average of all profile is [[0,1]]
    settlement_z_pairs : list of two element list of float, optional
        normalised depths to calculate normalised settlement between.
        e.g. surface settlement would be [[0, 1]]
    tvals : list of float
        times to calculate output at
    ppress_z_tval_indexes: list/array of int, slice, optional
        indexes of `tvals` at which to calculate ppress_z. i.e. only calc
        ppress_z at a subset of the `tvals` values.  default =
        slice(None, None) i.e. use all the `tvals`.
    avg_ppress_z_pairs_tval_indexes: list/array of int, slice, optional
        indexes of `tvals` at which to calculate avg_ppress_z_pairs.
        i.e. only calc avg_ppress_z_pairs at a subset of the `tvals` values.
        default = slice(None, None) i.e. use all the `tvals`.
    settlement_z_pairs_tval_indexes: list/array of int, slice, optional
        indexes of `tvals` at which to calculate settlement_z_pairs.
        i.e. only calc settlement_z_pairs at a subset of the `tvals` values.
        default = slice(None, None) i.e. use all the `tvals`.
    por, porc, pors : ndarray, only present if ppress_z is input
        calculated pore pressure at depths correspoinding to `ppress_z` and
        times corresponding to `tvals`.  This is an output array of
        size (len(ppress_z), len(tvals[ppress_z_tval_indexes])). porc and
        pors are pore pressure in column and soil.
    avp, avpc, avps : ndarray, only present if avg_ppress_z_pairs is input
        calculated average pore pressure between depths correspoinding to
        `avg_ppress_z_pairs` and times corresponding to `tvals`.  This is an
        output array of size
        (len(avg_ppress_z_pairs), len(tvals[avg_ppress_z_pairs_tval_indexes])).
        avpc and avps are average pore pressure in
        column and soil.
    set : ndarray, only present if settlement_z_pairs is input
        settlement between depths coreespoinding to `settlement_z_pairs` and
        times corresponding to `tvals`.  This is an output array of size
        (len(avg_ppress_z_pairs), len(tvals[settlement_z_pairs_tval_indexes]))
    implementation: ['vectorized', 'scalar', 'fortran'], optional
        where possible use the `implementation`, implementation.  'scalar'=
        python loops (slowest), 'vectorized' = numpy (fast), 'fortran' =
        fortran extension (fastest).  Note only some functions have multiple
        implementations.

    RLzero: float, optional
        reduced level of the top of the soil layer.  If RLzero is not None
        then all depths (in plots and results) will be transformed to an RL
        by RL = RLzero - z*H.  If RLzero is None (i.e. the default) then all
        depths will be reported  z*H (i.e. positive numbers).

    plot_properties : dict of dict, optional
        dictionary that overrides some of the plot properties.
        Each member of `plot_properties` will correspond to one of the plots.
        ==================  ============================================
        plot_properties    description
        ==================  ============================================
        por                 dict of prop to pass to pore pressure plot.
        avp                 dict of prop to pass to avergae pore
                            pressure plot.
        set                 dict of prop to pass to settlement plot.
        load                dict of prop to pass to pore pressure plot.
        material            dict of prop to pass to materials plot.

        ==================  ============================================
        see blah blah blah for what options can be specified in each plot dict.

    save_data_to_file: True/False, optional
        If True data will be saved to file.  Default=False
    save_figures_to_file: True/False
        If True then figures will be saved to file.  default=False
    show_figures: True/False, optional
        If True the after calculation figures will be shown on screen.
    directory : string, optional
        path to directory where files should be stored.  Default = None which
        will use the current working directory.  Note if you keep getting
        directory does not exist errors then try putting an r before the
        string definition. i.e. directory = r'C:\\Users\\...'
    overwrite : True/False, optional
        If True then exisitng files will be overwritten. default=False.
    prefix : string, optional
         filename prefix for all output files default = 'out'

    create_directory: True/Fase, optional
        If True a new sub-folder named `file_stem` will contain the output
        files. default=True
    data_ext: string, optional
        file extension for data files. default = '.csv'
    input_ext: string, optional
        file extension for original and parsed input files. default = ".py"
    figure_ext: string, optional
        file extension for figures, default = ".eps".  can be any valid
        matplotlib option for savefig.

    title: str, optional
        A title for the input file.  This will appear at the top of data files.
        Default = None, i.e. no title
    author: str, optional
        author of analysis. default= unknown

    Notes
    -----
    #TODO: explain lists of input must have same len.
    governing equation:



    References
    ----------
    All based on work by Dr Rohan Walker [1]_, [2]_, [3]_, [4]_

    .. [1] Walker, Rohan. 2006. 'Analytical Solutions for Modeling Soft Soil Consolidation by Vertical Drains'. PhD Thesis, Wollongong, NSW, Australia: University of Wollongong.
    .. [2] Walker, R., and B. Indraratna. 2009. 'Consolidation Analysis of a Stratified Soil with Vertical and Horizontal Drainage Using the Spectral Method'. Geotechnique 59 (5) (January): 439-449. doi:10.1680/geot.2007.00019.
    .. [3] Walker, Rohan, Buddhima Indraratna, and Nagaratnam Sivakugan. 2009. 'Vertical and Radial Consolidation Analysis of Multilayered Soil Using the Spectral Method'. Journal of Geotechnical and Geoenvironmental Engineering 135 (5) (May): 657-663. doi:10.1061/(ASCE)GT.1943-5606.0000075.
    .. [4] Walker, Rohan T. 2011. Vertical Drain Consolidation Analysis in One, Two and Three Dimensions'. Computers and Geotechnics 38 (8) (December): 1069-1077. doi:10.1016/j.compgeo.2011.07.006.

    """

    def _setup(self):

        self._attributes = (
            'H drn dT neig n '
            'mvref kvref kvcref khref khcref etref '
            'dTh dTv dTvc dThc '
            'mv kh kv et khc kvc '
            'surcharge_vs_depth surcharge_vs_time '
            'top_vs_time bot_vs_time '
            'ppress_z avg_ppress_z_pairs settlement_z_pairs tvals '
            'implementation ppress_z_tval_indexes '
            'avg_ppress_z_pairs_tval_indexes settlement_z_pairs_tval_indexes '
            'fixed_ppress surcharge_omega_phase '
            'fixed_ppress_omega_phase top_omega_phase bot_omega_phase '
            'pumping pumping_omega_phase '
            'RLzero '
            'prefix '

            ).split()

        self._attribute_defaults = {
            'H': 1.0, 'drn': 0, 'dT': 1.0, 'neig': 2, 'mvref':1.0,
            'kvref': 1.0, 'khref': 1.0, 'etref': 1.0,
            'kvcref': 1.0, 'khcref': 1.0,
            'implementation': 'vectorized',
            'ppress_z_tval_indexes': slice(None, None),
            'avg_ppress_z_pairs_tval_indexes': slice(None, None),
            'settlement_z_pairs_tval_indexes': slice(None, None),
            'prefix': 'speccon1dvrc_'
            }

        self._attributes_that_should_be_lists= (
            'surcharge_vs_depth surcharge_vs_time surcharge_omega_phase '
            'top_vs_time top_omega_phase '
            'bot_vs_time bot_omega_phase '
            'fixed_ppress fixed_ppress_omega_phase '
            'pumping pumping_omega_phase').split()

        self._attributes_that_should_have_same_x_limits = [
            'mv kv kh kvc khc et surcharge_vs_depth'.split()]

        self._attributes_that_should_have_same_len_pairs = [
            'surcharge_vs_depth surcharge_vs_time'.split(),
            'surcharge_vs_time surcharge_omega_phase'.split(),
            'top_vs_time top_omega_phase'.split(),
            'bot_vs_time bot_omega_phase'.split(),
            'fixed_ppress_omega_phase fixed_ppress'.split(),
            'pumping pumping_omega_phase'.split()] #pairs that should have the same length

        self._attributes_to_force_same_len = [
            "surcharge_vs_time surcharge_omega_phase".split(),
            "fixed_ppress fixed_ppress_omega_phase".split(),
            "top_vs_time top_omega_phase".split(),
            "bot_vs_time bot_omega_phase".split(),
            "pumping pumping_omega_phase".split()]

        self._zero_or_all = [
            'dTv kv'.split(),
            'surcharge_vs_depth surcharge_vs_time'.split(),
            ]
        self._at_least_one = [
            ['dTh'],
            ['dThc'],
            ['dTvc'],
            ['dTv'],
            ['mv'],
            ['n'],
            ('surcharge_vs_time top_vs_time '
                'bot_vs_time fixed_ppress pumping').split(),
            ['tvals'],
            'ppress_z avg_ppress_z_pairs settlement_z_pairs'.split()]

        self._one_implies_others = [
            ('surcharge_omega_phase surcharge_vs_depth '
                'surcharge_vs_time').split(),
            'fixed_ppress_omega_phase fixed_ppress'.split(),
            'top_omega_phase top_vs_time'.split(),
            'bot_omega_phase bot_vs_time'.split(),
            'pumping_omega_phase pumping'.split(),
            'dTh kh et'.split(),
            'dThc khc'.split(),
            'dTvc kvc et'.split(),
            'dTv kv'.split(),]


        #these explicit initializations are just to make coding easier
        self.H = self._attribute_defaults.get('H', None)
        self.drn = self._attribute_defaults.get('drn', None)
        self.dT = self._attribute_defaults.get('dT', None)
        self.neig = self._attribute_defaults.get('neig', None)
        self.mvref = self._attribute_defaults.get('mvref', None)
        self.kvref = self._attribute_defaults.get('kvref', None)
        self.khref = self._attribute_defaults.get('khref', None)
        self.kvcref = self._attribute_defaults.get('kvcref', None)
        self.khcref = self._attribute_defaults.get('khcref', None)
        self.etref = self._attribute_defaults.get('etref', None)
        self.dTh = None
        self.dTv = None
        self.dThc = None
        self.dTvc = None
        self.mv = None
        self.kh = None
        self.kv = None
        self.khc = None
        self.kvc = None
        self.et = None
        self.n = None
        self.surcharge_vs_depth = None
        self.surcharge_vs_time = None
        self.surcharge_omega_phase = None

        self.top_vs_time = None
        self.top_omega_phase = None
        self.bot_vs_time = None
        self.bot_omega_phase = None
        self.fixed_ppress_omega_phase = None
        self.fixed_ppress = None
        self.pumping = None
        self.pumping_omega_phase=None

        self.ppress_z = None
        self.avg_ppress_z_pairs = None
        self.settlement_z_pairs = None
        self.tvals = None
        self.RLzero = None

        self.plot_properties = self._attribute_defaults.get('plot_properties', None)

        self.ppress_z_tval_indexes = self._attribute_defaults.get('ppress_z_tval_indexes', None)
        self.avg_ppress_z_pairs_tval_indexes = self._attribute_defaults.get('avg_ppress_z_pairs_tval_indexes', None)
        self.settlement_z_pairs_tval_indexes = self._attribute_defaults.get('settlement_z_pairs_tval_indexes', None)


        return


#    def make_all(self):
#        """run checks, make all arrays, make output
#
#        Generally run this after input is in place (either through
#        initializing the class with a reader/text/fileobject or
#        through some other means)
#
#        See also
#        --------
#        check_input_attributes
#        make_time_independent_arrays
#        make_time_dependent_arrays
#        make_output
#
#        """
#
#        self.check_input_attributes()
#        self.make_time_independent_arrays()
#        self.make_time_dependent_arrays()
#        self.make_output()
#        return

    def make_time_independent_arrays(self):
        """make all time independent arrays


        See also
        --------
        self._make_m : make the basis function eigenvalues
        self._make_gam : make the mv dependent gamma matrix
        self._make_psi : make the kv, kh, et dependent psi matrix
        self._make_eigs_and_v : make eigenvalues, eigenvectors and I_gamv

        """


        self.alp = 1 / self.n**2


        self._make_m()
        self._make_gam()
        self._make_psi()
        self._make_eigs_and_v()

        return

    def make_time_dependent_arrays(self):
        """make all time dependent arrays

        See also
        --------
        self.make_E_Igamv_the()

        """
        self.tvals = np.asarray(self.tvals)
        self.make_E_Igamv_the()
        self.v_E_Igamv_the = np.dot(self.v, self.E_Igamv_the)
        return





    def make_output(self):
        """make all output"""

        header1 = "program: speccon1d_vrc; geotecha version: {}; author: {}; date: {}\n".format(self.version, self.author, time.strftime('%Y/%m/%d %H:%M:%S'))
        if not self.title is None:
            header1+= "{}\n".format(self.title)

        self._grid_data_dicts = []
        if not self.ppress_z is None:
            self._make_por()
            z = transformations.depth_to_reduced_level(
                np.asarray(self.ppress_z), self.H, self.RLzero)
            labels = ['{:.3g}'.format(v) for v in z]
            d = {'name': '_data_por',
                 'data': self.por.T,
                 'row_labels': self.tvals[self.ppress_z_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Pore pressure at depth'}
            self._grid_data_dicts.append(d)

            d = {'name': '_data_pors',
                 'data': self.pors.T,
                 'row_labels': self.tvals[self.ppress_z_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Pore pressure at depth in soil'}
            self._grid_data_dicts.append(d)

            d = {'name': '_data_porc',
                 'data': self.porc.T,
                 'row_labels': self.tvals[self.ppress_z_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Pore pressure at depth in column'}
            self._grid_data_dicts.append(d)

        if not self.avg_ppress_z_pairs is None:
            self._make_avp()
            z_pairs = transformations.depth_to_reduced_level(
                np.asarray(self.avg_ppress_z_pairs), self.H, self.RLzero)
            labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]
            d = {'name': '_data_avp',
                 'data': self.avp.T,
                 'row_labels': self.tvals[self.avg_ppress_z_pairs_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Average pore pressure between depths'}
            self._grid_data_dicts.append(d)

            d = {'name': '_data_avps',
                 'data': self.avps.T,
                 'row_labels': self.tvals[self.avg_ppress_z_pairs_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Average soil pore pressure between depths'}
            self._grid_data_dicts.append(d)

            d = {'name': '_data_avpc',
                 'data': self.avpc.T,
                 'row_labels': self.tvals[self.avg_ppress_z_pairs_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'Average column pore pressure between depths'}
            self._grid_data_dicts.append(d)

        if not self.settlement_z_pairs is None:
            self._make_set()
            z_pairs = transformations.depth_to_reduced_level(
                np.asarray(self.settlement_z_pairs), self.H, self.RLzero)
            labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]
            d = {'name': '_data_set',
                 'data': self.set.T,
                 'row_labels': self.tvals[self.settlement_z_pairs_tval_indexes],
                 'row_labels_label': 'Time',
                 'column_labels': labels,
                 'header': header1 + 'settlement between depths'}
            self._grid_data_dicts.append(d)
        return


    def _make_m(self):
        """make the basis function eigenvalues

        m in u = sin(m * Z)

        Notes
        -----

        .. math:: m_i =\\pi*\\left(i+1-drn/2\\right)

        for :math:`i = 1\:to\:neig-1`

        """

        if sum(v is None for v in[self.neig, self.drn])!=0:
            raise ValueError('neig and/or drn is not defined')
        self.m = integ.m_from_sin_mx(np.arange(self.neig), self.drn)
        return

#        self._make_gams()

    def _make_gam(self):
        """make the mv dependant gam matrix

        """

        self.gam = integ.pdim1sin_af_linear(
                        self.m, self.mv, implementation=self.implementation)
        self.gam[np.abs(self.gam)<1e-8] = 0.0

        return


    def _make_psi(self):
        """make all the kv, kh, kvc, khc, et dependant psi matrices



        """


        #psi_sv, kv part
        if sum([v is None for v in [self.kv, self.dTv]])==0:
            self.psi_sv = (self.dTv / self.dT *
                integ.pdim1sin_D_aDf_linear(self.m, self.kv,
                    implementation=self.implementation))

        #psi_sh, kh & et part
        if sum([v is None for v in [self.kh, self.et, self.dTh]])==0:
            kh, et = pwise.polyline_make_x_common(self.kh, self.et)#
            self.psi_sh = (self.dTh / self.dT *
                integ.pdim1sin_abf_linear(self.m, self.kh, self.et,
                                          implementation=self.implementation))
        #psi_s
            self.psi_s = self.psi_sh - self.psi_sv

        #psi_cv, kvc part
        if sum([v is None for v in [self.kvc, self.dTvc]])==0:
            self.psi_cv = (self.dTvc / self.dT *
                integ.pdim1sin_D_aDf_linear(self.m, self.kvc,
                                        implementation=self.implementation))

        #psi_ch, khc
        if sum([v is None for v in [self.khc, self.dThc]])==0:
            self.psi_ch = (self.dThc / self.dT *
                integ.pdim1sin_af_linear(self.m, self.khc,
                                         implementation=self.implementation))
        #psi_c
            self.psi_c = self.psi_ch - self.psi_cv




        Ibet = np.bmat([[np.diag([1.0 - self.alp] * self.neig),
                         np.diag([self.alp] * self.neig),
                         np.zeros((self.neig, self.neig))],
                        [self.psi_s,
                         -self.psi_c ,
                         self.psi_ch - self.psi_sh ],
                        [self.psi_sh - self.alp * self.psi_sv,
                         self.alp * self.psi_cv,
                         -self.psi_sh]])

        Ibet = np.asarray(Ibet) # np.bmat returns an array

        self.bet = np.linalg.inv(Ibet)

        self.bet00 = self.bet[:self.neig, :self.neig]
        self.bet01 = self.bet[:self.neig, self.neig:2 * self.neig]
        self.bet02 = self.bet[:self.neig, 2 * self.neig:]

        self.bet10 = self.bet[self.neig: 2*self.neig, :self.neig]
        self.bet11 = self.bet[self.neig: 2*self.neig, self.neig:2 * self.neig]
        self.bet12 = self.bet[self.neig: 2*self.neig, 2 * self.neig:]

        self.bet20 = self.bet[2*self.neig:, :self.neig]
        self.bet21 = self.bet[2*self.neig:, self.neig:2 * self.neig]
        self.bet22 = self.bet[2*self.neig:, 2 * self.neig:]


        self.psi = (1 - self.alp) * np.dot(self.psi_sv, self.bet00)
        self.psi += self.alp * np.dot(self.psi_cv, self.bet10)
        self.psi *=-1.0


#        #fixed pore pressure part
#        if not self.fixed_ppress is None:
#            for (zfixed, pseudo_k, mag_vs_time) in self.fixed_ppress:
#                self.psi += pseudo_k / self.dT * np.sin(self.m[:, np.newaxis] * zfixed) * np.sin(self.m[np.newaxis, :] * zfixed)

        return

    def _make_eigs_and_v(self):
        """make Igam_psi, v and eigs, and Igamv



        Finds the eigenvalues, `self.eigs`, and eigenvectors, `self.v` of
        inverse(gam)*psi.  Once found the matrix inverse(gamma*v), `self.Igamv`
        is determined.

        Notes
        -----
        From the original equation

        .. math:: \\mathbf{\\Gamma}\\mathbf{A}'=\\mathbf{\\Psi A}+loading\\:terms

        `self.eigs` and `self.v` are the eigenvalues and eigenvegtors of the matrix `self.Igam_psi`

        .. math:: \\left(\\mathbf{\\Gamma}^{-1}\\mathbf{\\Psi}\\right)

        """

        self.psi[np.abs(self.psi) < 1e-8] = 0.0
        Igam_psi = np.dot(np.linalg.inv(self.gam), self.psi)
        self.eigs, self.v = np.linalg.eig(Igam_psi)
        self.v = np.asarray(self.v)
        self.Igamv = np.linalg.inv(np.dot(self.gam, self.v))

        return

    def make_E_Igamv_the(self):
        """sum contributions from all loads

        Calculates all contributions to E*inverse(gam*v)*theta part of solution
        u=phi*vE*inverse(gam*v)*theta. i.e. surcharge, vacuum, top and bottom
        pore pressure boundary conditions. `make_load_matrices will create
        `self.E_Igamv_the`.  `self.E_Igamv_the`  is an array
        of size (neig, len(tvals)). So the columns are the column array
        E*inverse(gam*v)*theta calculated at each output time.  This will allow
        us later to do u = phi*v*self.E_Igamv_the

        See also
        --------
        _make_E_Igamv_the_surcharge :  surchage contribution
        _make_E_Igamv_the_BC : top boundary pore pressure contribution
        _make_E_Igamv_the_bot : bottom boundary pore pressure contribution
        """

        self.E_Igamv_the = np.zeros((self.neig, len(self.tvals)))

        if sum([v is None for
                v in [self.surcharge_vs_depth, self.surcharge_vs_time]])==0:
            self._make_E_Igamv_the_surcharge()
            self.E_Igamv_the += self.E_Igamv_the_surcharge

        if not self.top_vs_time is None or not self.bot_vs_time is None:
            self._make_E_Igamv_the_BC()
            self.E_Igamv_the += self.E_Igamv_the_BC
#        if not self.fixed_ppress is None:
#            self._make_E_Igamv_the_fixed_ppress()
#            self.E_Igamv_the +=self.E_Igamv_the_fixed_ppress
#        if not self.pumping is None:
#            self._make_E_Igamv_the_pumping()
#            self.E_Igamv_the += self.E_Igamv_the_pumping

        return

    def _make_E_Igamv_the_surcharge(self):
        """make the surcharge loading matrices

        Make the E*inverse(gam*v)*theta part of solution u=phi*vE*inverse(gam*v)*theta.
        The contribution of each surcharge load is added and put in
        `self.E_Igamv_the_surcharge`. `self.E_Igamv_the_surcharge` is an array
        of size (neig, len(tvals)). So the columns are the column array
        E*inverse(gam*v)*theta calculated at each output time.  This will allow
        us later to do u = phi*v*self.E_Igamv_the_surcharge

        Notes
        -----
        Assuming the load are formulated as the product of separate time and depth
        dependant functions:

        .. math:: \\sigma\\left({Z,t}\\right)=\\sigma\\left({Z}\\right)\\sigma\\left({t}\\right)

        the solution to the consolidation equation using the spectral method has
        the form:

        .. math:: u\\left(Z,t\\right)=\\mathbf{\\Phi v E}\\left(\\mathbf{\\Gamma v}\\right)^{-1}\\mathbf{\\theta}

        `_make_E_Igamv_the_surcharge` will create `self.E_Igamv_the_surcharge` which is
        the :math:`\\mathbf{E}\\left(\\mathbf{\\Gamma v}\\right)^{-1}\\mathbf{\\theta}`
        part of the solution for all surcharge loads

        """
        self.E_Igamv_the_surcharge = speccon1d.dim1sin_E_Igamv_the_aDmagDt_bilinear(self.m, self.eigs, self.tvals, self.Igamv, self.mv, self.surcharge_vs_depth, self.surcharge_vs_time, self.surcharge_omega_phase, self.dT)
#        self.E_Igamv_the_surcharge = (
#            speccon1d.dim1sin_E_Igamv_the_aDmagDt_bilinear(
#                self.m, self.eigs, self.tvals, self.Igamv, self.mv,
#                self.surcharge_vs_depth, self.surcharge_vs_time,
#                self.surcharge_omega_phase, self.dT))
        return


#    def _make_E_Igamv_the_fixed_ppress(self):
#        """make the fixed pore pressure loading matrices
#
#        """
#
#        self.E_Igamv_the_fixed_ppress = np.zeros((self.neig, len(self.tvals)))
#
#        if not self.fixed_ppress is None:
#            zvals = [v[0] for v in self.fixed_ppress]
#            pseudo_k = [v[1] for v in self.fixed_ppress]
#            mag_vs_time = [v[2] for v in self.fixed_ppress]
#            self.E_Igamv_the_fixed_ppress += (
#                speccon1d.dim1sin_E_Igamv_the_deltamag_linear(
#                    self.m, self.eigs, self.tvals, self.Igamv,
#                    zvals, pseudo_k, mag_vs_time,
#                    self.fixed_ppress_omega_phase, self.dT))
#
#
#    def _make_E_Igamv_the_pumping(self):
#        """make the pumping loading matrices
#
#        """
#
#        self.E_Igamv_the_pumping = np.zeros((self.neig, len(self.tvals)))
#
#        if not self.pumping is None:
#            zvals = [v[0] for v in self.pumping]
#            pseudo_k = [1 for v in self.pumping]
#            #dividing by mvref*H is because input pumping velocities need to
#            # normalised
#            mag_vs_time = [v[1] / (self.mvref * self.H) for v in self.pumping]
#            self.E_Igamv_the_pumping += (
#                speccon1d.dim1sin_E_Igamv_the_deltamag_linear(
#                    self.m, self.eigs, self.tvals, self.Igamv,
#                    zvals, pseudo_k, mag_vs_time,
#                    self.pumping_omega_phase, self.dT))


    def _normalised_bot_vs_time(self):
        """Normalise bot_vs_time when drn=1, i.e. bot_vs_time is a gradient

        Multiplie each bot_vs_time PolyLine by self.H

        Returns
        -------
        bot_vs_time : list of Polylines, or None
            bot_vs_time normalised by H

        """

        if not self.bot_vs_time is None:
            if self.drn == 1:
                bot_vs_time = ([vs_time * self.H for
                                vs_time in self.bot_vs_time])
            else:
                bot_vs_time = self.bot_vs_time
        else:
            bot_vs_time = None
        return bot_vs_time

    def _make_E_Igamv_the_BC(self):
        """make the boundary condition loading matrices

        """
        self.E_Igamv_the_BC = np.zeros((self.neig, len(self.tvals)))
        bot_vs_time = self._normalised_bot_vs_time()


        #mv * du/dt component
        self.E_Igamv_the_BC -= (
            speccon1d.dim1sin_E_Igamv_the_BC_aDfDt_linear(
                self.drn, self.m, self.eigs, self.tvals,
                self.Igamv, self.mv, self.top_vs_time, bot_vs_time,
                self.top_omega_phase, self.bot_omega_phase, self.dT))


        G = np.diag([self.alp]*self.neig)
        G -= (1-self.alp) * self.psi_sv.dot((self.bet01 + self.alp*self.bet02))
        G -= self.alp * self.psi_cv.dot((self.bet11 + self.alp*self.bet12))

        #dTv * d/dZ(kv * du/dZ) component
        if sum([v is None for v in [self.kv, self.dTv]])==0:
            if self.dTv!=0:
                self.E_Igamv_the_BC += (self.dTv *
                    speccon1d.dim1sin_E_Igamv_the_BC_D_aDf_linear(
                        self.drn, self.m, self.eigs, self.tvals,
                        self.Igamv.dot(np.identity(self.neig, dtype=float)-G),
                        self.kv, self.top_vs_time,
                        bot_vs_time, self.top_omega_phase,
                        self.bot_omega_phase, self.dT))

        #dTvc * d/dZ(kvc * du/dZ) component
        if sum([v is None for v in [self.kvc, self.dTvc]])==0:
            if self.dTvc!=0:
                self.E_Igamv_the_BC += (self.dTvc *
                    speccon1d.dim1sin_E_Igamv_the_BC_D_aDf_linear(
                        self.drn, self.m, self.eigs, self.tvals,
                        self.Igamv.dot(np.identity(self.neig, dtype=float)-G),
                        self.kvc, self.top_vs_time,
                        bot_vs_time, self.top_omega_phase,
                        self.bot_omega_phase, self.dT))


#        #the pseudo_k * delta(z-zfixed)*u component, i.e. the fixed_ppress part
#        if not self.fixed_ppress is None:
#            zvals = [v[0] for v in self.fixed_ppress]
#            pseudo_k = [v[1] for v in self.fixed_ppress]
#            self.E_Igamv_the_BC -= (
#                speccon1d.dim1sin_E_Igamv_the_BC_deltaf_linear(
#                    self.drn, self.m, self.eigs, self.tvals,
#                    self.Igamv, zvals, pseudo_k, self.top_vs_time,
#                    bot_vs_time, self.top_omega_phase,
#                    self.bot_omega_phase, self.dT))


    def _make_por(self):
        """make the pore pressure output, us, uc, and u

        makes `self.por`, the average pore pressure at depths corresponding to
        self.ppress_z and times corresponding to self.tvals.  `self.por`  has size
        (len(ppress_z), len(tvals)).

        Notes
        -----
        Solution to consolidation equation with spectral method for pore pressure at depth is :

        .. math:: u\\left(Z,t\\right)=\\mathbf{\\Phi v E}\\left(\\mathbf{\\Gamma v}\\right)^{-1}\\mathbf{\\theta}+u_{top}\\left({t}\\right)\\left({1-Z}\\right)+u_{bot}\\left({t}\\right)\\left({Z}\\right)

        For pore pressure :math:`\\Phi` is simply :math:`sin\\left({mZ}\\right)` for each value of m


        """

        bot_vs_time = self._normalised_bot_vs_time()
        tvals = self.tvals[self.ppress_z_tval_indexes]
        #average pore pressure at depth
        self.por = speccon1d.dim1sin_f(self.m, self.ppress_z,
            tvals,
            self.v_E_Igamv_the[:, self.ppress_z_tval_indexes],
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
#        self.por=np.asarray(self.por)

        #soil pore poressure at depth
        self.pors = speccon1d.dim1sin_f(self.m, self.ppress_z,
            tvals,
            self.bet00.dot(self.v_E_Igamv_the[:, self.ppress_z_tval_indexes]),
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
        if not self.top_vs_time is None or not self.bot_vs_time is None:
            a = self.dTv * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet01 + self.alp * self.bet02),
                    self.kv, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            b = self.dTvc * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet01 + self.alp * self.bet02),
                    self.kvc, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            self.pors += speccon1d.dim1sin_f(self.m, self.ppress_z,
                                             tvals, a+b, self.drn)
#        self.pors = np.asarray(self.pors)

        #column pore pressure at depth
        self.porc = speccon1d.dim1sin_f(self.m, self.ppress_z,
            tvals,
            self.bet10.dot(self.v_E_Igamv_the[:, self.ppress_z_tval_indexes]),
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
        if not self.top_vs_time is None or not self.bot_vs_time is None:
            a = self.dTv * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet11 + self.alp * self.bet12),
                    self.kv, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            b = self.dTvc * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet11 + self.alp * self.bet12),
                    self.kvc, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            self.porc += speccon1d.dim1sin_f(self.m, self.ppress_z,
                                             tvals, a+b, self.drn)
#        self.porc = np.asarray(self.porc)
        return

#    def _make_porwell(self):
#        """make the well/drain pore pressure output
#
#        """
#        bot_vs_time = self._normalised_bot_vs_time()
#
#        tvals = self.tvals[self.ppress_z_tval_indexes]
#        #phi * Ipsi_w * psi_s * v_E_Igamv_the part, including BC adjustment
#        a = np.dot(self.Ipsi_w, self.psi_s)
#        v_E_Igamv_the = np.dot(a, self.v_E_Igamv_the[:, self.ppress_z_tval_indexes])
#        self.porwell = speccon1d.dim1sin_f(self.m, self.ppress_z, tvals, v_E_Igamv_the, self.drn, self.top_vs_time, self.bot_vs_time, self.top_omega_phase, self.bot_omega_phase)
#
#
#        #1/(n**2-1) * (phi * Ipsi_w * psi_s * thetaT(t) + phi * Ipsi_w * psi_s * thetaT(t))
#        v_E_Igamv_the = speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
#                self.drn, self.m, self.eigs, tvals, self.Ipsi_w,
#                self.kw, self.top_vs_time, bot_vs_time,
#                top_omega_phase=None, bot_omega_phase=None)
#
#
#        self.porwell += speccon1d.dim1sin_f(self.m, self.ppress_z,
#                                            tvals, v_E_Igamv_the, self.drn)
#        return


    def _make_avp(self):
        """calculate average pore pressure, for us uc and u

        makes `self.avp`, the average pore pressure at depths corresponding to
        self.avg_ppress_z_pairs and times corresponding to self.tvals.  `self.avp`  has size
        (len(ppress_z), len(tvals)).


        Notes
        -----
        The average pore pressure between Z1 and Z2 is given by:

        .. math:: \\overline{u}\\left(\\left({Z_1,Z_2}\\right),t\\right)=\\int_{Z_1}^{Z_2}{\\mathbf{\\Phi v E}\\left(\\mathbf{\\Gamma v}\\right)^{-1}\\mathbf{\\theta}+u_{top}\\left({t}\\right)\\left({1-Z}\\right)+u_{bot}\\left({t}\\right)\\left({Z}\\right)\,dZ}/\\left({Z_2-Z_1}\\right)

        """
        bot_vs_time = self._normalised_bot_vs_time()
        tvals = self.tvals[self.avg_ppress_z_pairs_tval_indexes]
        v_E_Igamv_the = self.v_E_Igamv_the[:self.neig, self.avg_ppress_z_pairs_tval_indexes]
        #average pore pressure at depth
        self.avp = speccon1d.dim1sin_avgf(self.m, self.avg_ppress_z_pairs,
            tvals,
            v_E_Igamv_the,
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
#        self.avp = np.asarray(self.avp)
        #soil pore poressure at depth
        self.avps = speccon1d.dim1sin_avgf(self.m, self.avg_ppress_z_pairs,
            tvals,
            self.bet00.dot(v_E_Igamv_the),
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
        if not self.top_vs_time is None or not self.bot_vs_time is None:
            a = self.dTv * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet01 + self.alp * self.bet02),
                    self.kv, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            b = self.dTvc * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet01 + self.alp * self.bet02),
                    self.kvc, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            self.avps += speccon1d.dim1sin_avgf(self.m, self.avg_ppress_z_pairs,
                                             tvals, a+b, self.drn)
#        self.avps = np.asarray(self.avps)

        #column pore pressure at depth
        self.avpc = speccon1d.dim1sin_avgf(self.m, self.avg_ppress_z_pairs,
            tvals,
            self.bet10.dot(v_E_Igamv_the),
            self.drn, self.top_vs_time, bot_vs_time,
            self.top_omega_phase, self.bot_omega_phase)
        if not self.top_vs_time is None or not self.bot_vs_time is None:
            a = self.dTv * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet11 + self.alp * self.bet12),
                    self.kv, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            b = self.dTvc * speccon1d.dim1sin_foft_Ipsiw_the_BC_D_aDf_linear(
                    self.drn, self.m, self.eigs,
                    tvals,
                    (self.bet11 + self.alp * self.bet12),
                    self.kvc, self.top_vs_time, bot_vs_time,
                    self.top_omega_phase, self.bot_omega_phase)
            self.avpc += speccon1d.dim1sin_avgf(self.m, self.avg_ppress_z_pairs,
                                             tvals, a+b, self.drn)
#        self.avpc = np.asarray(self.avpc)


        return

    def _make_set(self):
        """calculate settlement

        makes `self.set`, the average pore pressure at depths corresponding to
        self.settlement_z_pairs and times corresponding to self.tvals.  `self.set`  has size
        (len(ppress_z), len(tvals)).


        Notes
        -----
        The average settlement between Z1 and Z2 is given by:

        .. math:: \\overline{\\rho}\\left(\\left({Z_1,Z_2}\\right),t\\right)=\\int_{Z_1}^{Z_2}{m_v\\left({Z}\\right)\\left({\\sigma\\left({Z,t}\\right)-u\\left({Z,t}\\right)}\\right)\\,dZ}


        .. math:: \\overline{\\rho}\\left(\\left({Z_1,Z_2}\\right),t\\right)=\\int_{Z_1}^{Z_2}{m_v\\left({Z}\\right)\\sigma\\left({Z,t}\\right)\\,dZ}+\\int_{Z_1}^{Z_2}{m_v\\left({Z}\\right)\\left({\\mathbf{\\Phi v E}\\left(\\mathbf{\\Gamma v}\\right)^{-1}\\mathbf{\\theta}+u_{top}\\left({t}\\right)\\left({1-Z}\\right)+u_{bot}\\left({t}\\right)\\left({Z}\\right)}\\right)\\,dZ}

        """

        bot_vs_time = self._normalised_bot_vs_time()
        z1 = np.asarray(self.settlement_z_pairs)[:,0]
        z2 = np.asarray(self.settlement_z_pairs)[:,1]

        self.set=-speccon1d.dim1sin_integrate_af(self.m, self.settlement_z_pairs, self.tvals[self.settlement_z_pairs_tval_indexes],
                                       self.v_E_Igamv_the[:,self.settlement_z_pairs_tval_indexes],
                                        self.drn, self.mv, self.top_vs_time, bot_vs_time, self.top_omega_phase, self.bot_omega_phase)

        if not self.surcharge_vs_time is None:
            self.set += pwise.pxa_ya_cos_multiply_integrate_x1b_x2b_y1b_y2b_multiply_x1c_x2c_y1c_y2c_between_super(self.surcharge_vs_time, self.surcharge_vs_depth, self.mv, self.tvals[self.settlement_z_pairs_tval_indexes], z1, z2, omega_phase = self.surcharge_omega_phase, achoose_max=True)

        self.set *= self.H * self.mvref
        return


#    def _plot_porwell(self):
#        """plot depth vs well/drain pore pressure for various times
#
#        """
#        t = self.tvals[self.ppress_z_tval_indexes]
#        line_labels = ['{:.3g}'.format(v) for v in t]
#        por_prop = self.plot_properties.pop('porwell', dict())
#        if not 'xlabel' in por_prop:
#            por_prop['xlabel'] = 'Drain Pore pressure'
#
#        #to do
#        fig_porwell = geotecha.plotting.one_d.plot_vs_depth(self.porwell, self.ppress_z,
#                                      line_labels=line_labels, H = self.H,
#                                      RLzero=self.RLzero,
#                                      prop_dict=por_prop)
#        return fig_porwell

    def _plot_pors(self):
        """plot soil depth vs pore pressure for various times

        """
        t = self.tvals[self.ppress_z_tval_indexes]
        line_labels = ['{:.3g}'.format(v) for v in t]
        por_prop = self.plot_properties.pop('pors', dict())
        if not 'xlabel' in por_prop:
            por_prop['xlabel'] = 'Soil pore pressure'

        #to do
        fig_por = geotecha.plotting.one_d.plot_vs_depth(self.pors, self.ppress_z,
                                      line_labels=line_labels, H = self.H,
                                      RLzero=self.RLzero,
                                      prop_dict=por_prop)
        return fig_por
    def _plot_porc(self):
        """plot column depth vs pore pressure for various times

        """
        t = self.tvals[self.ppress_z_tval_indexes]
        line_labels = ['{:.3g}'.format(v) for v in t]
        porc_prop = self.plot_properties.pop('porc', dict())
        if not 'xlabel' in porc_prop:
            porc_prop['xlabel'] = 'Column pore pressure'

        #to do
        fig_porc = geotecha.plotting.one_d.plot_vs_depth(self.porc, self.ppress_z,
                                      line_labels=line_labels, H = self.H,
                                      RLzero=self.RLzero,
                                      prop_dict=porc_prop)
        return fig_porc

    def _plot_por(self):
        """plot depth vs pore pressure for various times

        """
        t = self.tvals[self.ppress_z_tval_indexes]
        line_labels = ['{:.3g}'.format(v) for v in t]
        por_prop = self.plot_properties.pop('por', dict())
        if not 'xlabel' in por_prop:
            por_prop['xlabel'] = 'Pore pressure'

        #to do
        fig_por = geotecha.plotting.one_d.plot_vs_depth(self.por, self.ppress_z,
                                      line_labels=line_labels, H = self.H,
                                      RLzero=self.RLzero,
                                      prop_dict=por_prop)
        return fig_por

    def _plot_avp(self):
        """plot average pore pressure vs time for various depth intervals

        """

        t = self.tvals[self.avg_ppress_z_pairs_tval_indexes]
        z_pairs = transformations.depth_to_reduced_level(
            np.asarray(self.avg_ppress_z_pairs), self.H, self.RLzero)
        line_labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]

        avp_prop = self.plot_properties.pop('avp', dict())
        if not 'ylabel' in avp_prop:
            avp_prop['ylabel'] = 'Average pore pressure'
        fig_avp = geotecha.plotting.one_d.plot_vs_time(t, self.avp.T,
                           line_labels=line_labels,
                           prop_dict=avp_prop)
        return fig_avp

    def _plot_avps(self):
        """plot average soil pore pressure vs time for various depth intervals

        """

        t = self.tvals[self.avg_ppress_z_pairs_tval_indexes]
        z_pairs = transformations.depth_to_reduced_level(
            np.asarray(self.avg_ppress_z_pairs), self.H, self.RLzero)
        line_labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]

        avp_prop = self.plot_properties.pop('avps', dict())
        if not 'ylabel' in avp_prop:
            avp_prop['ylabel'] = 'Average soil pore pressure'
        fig_avp = geotecha.plotting.one_d.plot_vs_time(t, self.avps.T,
                           line_labels=line_labels,
                           prop_dict=avp_prop)
        return fig_avp

    def _plot_avpc(self):
        """plot average column pore pressure vs time for various depth intervals

        """

        t = self.tvals[self.avg_ppress_z_pairs_tval_indexes]
        z_pairs = transformations.depth_to_reduced_level(
            np.asarray(self.avg_ppress_z_pairs), self.H, self.RLzero)
        line_labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]

        avp_prop = self.plot_properties.pop('avpc', dict())
        if not 'ylabel' in avp_prop:
            avp_prop['ylabel'] = 'Average column pore pressure'
        fig_avp = geotecha.plotting.one_d.plot_vs_time(t, self.avpc.T,
                           line_labels=line_labels,
                           prop_dict=avp_prop)
        return fig_avp

    def _plot_set(self):
        """plot settlement vs time for various depth intervals


        """
        t = self.tvals[self.settlement_z_pairs_tval_indexes]
        z_pairs = transformations.depth_to_reduced_level(
            np.asarray(self.settlement_z_pairs), self.H, self.RLzero)
        line_labels = ['{:.3g} to {:.3g}'.format(z1, z2) for z1, z2 in z_pairs]

        set_prop = self.plot_properties.pop('set', dict())
        if not 'ylabel' in set_prop:
            set_prop['ylabel'] = 'Settlement'
        fig_set = geotecha.plotting.one_d.plot_vs_time(t, self.set.T,
                           line_labels=line_labels,
                           prop_dict=set_prop)
        fig_set.gca().invert_yaxis()

        return fig_set

    def produce_plots(self):
        """produce plots of analysis"""

        geotecha.plotting.one_d.pleasing_defaults()

#        matplotlib.rcParams['figure.dpi'] = 80
#        matplotlib.rcParams['savefig.dpi'] = 80

        matplotlib.rcParams.update({'font.size': 11})
        matplotlib.rcParams.update({'font.family': 'serif'})

        self._figures=[]
        #por and porwell
        if not self.ppress_z is None:
            f=self._plot_por()
            title = 'fig_por'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

            f=self._plot_pors()
            title = 'fig_pors'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

            f=self._plot_porc()
            title = 'fig_porc'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

        if not self.avg_ppress_z_pairs is None:
            f=self._plot_avp()
            title = 'fig_avp'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

            f=self._plot_avps()
            title = 'fig_avps'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

            f=self._plot_avpc()
            title = 'fig_avpc'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)

        #settle
        if not self.settlement_z_pairs is None:
            f=self._plot_set()
            title = 'fig_set'
            f.set_label(title)
            f.canvas.manager.set_window_title(title)
            self._figures.append(f)
        #loads
        f=self._plot_loads()
        title = 'fig_loads'
        f.set_label(title)
        f.canvas.manager.set_window_title(title)
        self._figures.append(f)

        #materials
        f=self._plot_materials()
        self._figures.append(f)
        title = 'fig_materials'
        f.set_label(title)
        f.canvas.manager.set_window_title(title)

    def _plot_materials(self):

        material_prop = self.plot_properties.pop('material', dict())

        z_x=[]
        xlabels=[]
        if not self.mv is None:
            z_x.append(self.kv)
            xlabels.append('$m_v/\\overline{{m}}_v$, $\\left'
                '(\\overline{{m}}_v={:g}\\right)$'.format(self.mvref))
        if not self.kv is None:
            z_x.append(self.kv)
            xlabels.append('$k_v/\\overline{{k}}_v$, $\\left(\\overline{{k}}_v={:g}\\right)$'.format(self.kvref))
        if not self.khc is None:
            z_x.append(self.kvc)
            xlabels.append('$k_{{vc}}/\\overline{{k}}_{{vc}}$, $\\left(\\overline{{k}}_{{vc}}={:g}\\right)$'.format(self.kvcref))
        if not self.kh is None:
            z_x.append(self.kh)
            xlabels.append('$k_h/\\overline{{k}}_h$, $\\left(\\overline{{k}}_h={:g}\\right)$'.format(self.khref))
        if not self.khc is None:
            z_x.append(self.khc)
            xlabels.append('$k_{{hc}}/\\overline{{k}}_{{hc}}$, $\\left(\\overline{{k}}_{{hc}}={:g}\\right)$'.format(self.khcref))
        if not self.et is None:
            z_x.append(self.et)
            xlabels.append('$\\eta/\\overline{{\\eta}}$, $\\left(\\overline{{\\eta}}={:g}\\right)$'.format(self.etref))


        return (geotecha.plotting.one_d.plot_single_material_vs_depth(z_x, xlabels, H = self.H,
                            RLzero = self.RLzero,prop_dict = material_prop))
    def _plot_loads(self):
        """plot loads

        """

        load_prop = self.plot_properties.pop('load', dict())
        load_triples=[]
        load_names = []
        ylabels=[]
        #surcharge
        if not self.surcharge_vs_time is None:
            load_names.append('surch')
            ylabels.append('Surcharge')
            load_triples.append(
                [(vs_time, vs_depth, omega_phase) for
                    vs_time, vs_depth, omega_phase  in
                    zip(self.surcharge_vs_time, self.surcharge_vs_depth,
                    self.surcharge_omega_phase)])

#        if not self.vacuum_vs_time is None:
#            load_names.append('vac')
#            ylabels.append('Vacuum')
#            load_triples.append(
#                [(vs_time, vs_depth, omega_phase) for
#                    vs_time, vs_depth, omega_phase  in
#                    zip(self.vacuum_vs_time, self.vacuum_vs_depth,
#                    self.vacuum_omega_phase)])

        if not self.top_vs_time is None:
            load_names.append('top')
            ylabels.append('Top boundary')
            load_triples.append(
                [(vs_time, ([0],[1]), omega_phase) for
                    vs_time, omega_phase  in
                    zip(self.top_vs_time, self.top_omega_phase)])

        if not self.bot_vs_time is None:
            #TODO: maybe if drn = 1, multiply bot_vs_time by H to give actual
            # gradient rather than normalised.
            load_names.append('bot')
            ylabels.append('Bot boundary')
            load_triples.append(
                [(vs_time, ([1],[1]), omega_phase) for
                    vs_time, omega_phase  in
                    zip(self.bot_vs_time, self.bot_omega_phase)])

#        if not self.fixed_ppress is None:
#            load_names.append('fixed p')
#            ylabels.append('Fixed ppress')
#            fixed_ppress_triples=[]
#            for (zfixed, pseudo_k,
#                     vs_time), omega_phase in zip(self.fixed_ppress,
#                                                self.fixed_ppress_omega_phase):
#
#                if vs_time is None:
#                    vs_time = PolyLine([self.tvals[0], self.tvals[-1]], [0,0])
#
#                vs_depth = ([zfixed], [1])
#                fixed_ppress_triples.append((vs_time,vs_depth, omega_phase))
#
#            load_triples.append(fixed_ppress_triples)
#
#        if not self.pumping is None:
#            #TODO: maybe multiply mag_vs_time by H and mvref to atual pumping
#            #velocity rather than normalised.
#            # gradient rather than normalised.
#            load_names.append('pump')
#            ylabels.append('Pumping velocity')
#            pumping_triples=[]
#            for (zpump, vs_time), omega_phase in zip(self.pumping,
#                                                    self.pumping_omega_phase):
#                vs_depth = ([zpump], [1])
#                pumping_triples.append((vs_time, vs_depth, omega_phase))
#
#            load_triples.append(pumping_triples)

        return (geotecha.plotting.one_d.plot_generic_loads(load_triples, load_names,
                    ylabels=ylabels, H = self.H, RLzero=self.RLzero,
                    prop_dict=load_prop))


def main():
    a = GenericInputFileArgParser(obj=Speccon1dVR,
                                  methods=[('make_all', [], {})],
                                 pass_open_file=True)

    a.main()

if __name__ == '__main__':
#    import nose
#    nose.runmodule(argv=['nose', '--verbosity=3', '--with-doctest'])
##    nose.runmodule(argv=['nose', '--verbosity=3'])
#    main()
    my_code = textwrap.dedent("""\
#from geotecha.piecewise.piecewise_linear_1d import PolyLine
#import numpy as np
H = 1
drn = 1
dT = 1
dTh = 0.5
dTv = 0.1 * 0.25
dThc = 1000
dTvc = 1000
neig = 20


mvref = 2.0
kvref = 1.0
khref = 1.0
kvcref = 1.0
khcref = 1.0
etref = 1.0


re=1.5
rc=0.1
n = re/rc

# work out lumped mv parameter
mv_x = np.array([0.0,1.0])
ms_y = np.array([0.5,0.5])
mc_y = np.array([0.5,0.5])/200
mv_y = ms_y/(1+(ms_y/mc_y-1)/n**2)
mv = PolyLine(mv_x, mv_y)

kh = PolyLine([0,1], [1,1])
kv = PolyLine([0,1], [5,5])
khc = PolyLine([0,1], [1,1])
kvc = PolyLine([0,1], [5,5])

#et = PolyLine([0,0.48,0.48, 0.52, 0.52,1], [0, 0,1,1,0,0])
et = PolyLine([0,1], [1,1])

#surcharge_vs_depth = PolyLine([0,1], [1,1]),
#surcharge_vs_time = PolyLine([0,0,10], [0,10,10])
#surcharge_omega_phase = (2*np.pi*0.5, -np.pi/2)
surcharge_vs_depth = PolyLine([0,1], [1,1])
surcharge_vs_time = PolyLine([0,0,10], [0,10,10])
#surcharge_omega_phase = [(2*np.pi*0.5, -np.pi/2), None]


#dT = 1
#dTh = 0.5
#dTv = 0.1 * 0.25
#mv = PolyLine([0,1], [0.5, 0.5])
#surcharge_vs_depth = [PolyLine([0,1], [1,1]), PolyLine([0,1], [1,1])]
#surcharge_vs_time = [PolyLine([0,0,10], [0,10,10]), PolyLine([0,0,10], [0,10,10])]



#top_vs_time = PolyLine([0,0.0,10], [0,-100,-100])
#top_omega_phase = (2*np.pi*1, -np.pi/2)
#bot_vs_time = PolyLine([0,0.0,3], [0,-10,-10])
#bot_vs_time = PolyLine([0,0.0,10], [0, -10, -10])

#bot_vs_time = PolyLine([0,0.0,0.4,10], [0, -2500, -250, -210])
#bot_omega_phase = (2*np.pi*2, -np.pi/2)


#fixed_ppress = (0.2, 1000, PolyLine([0, 0.0, 8], [0,-30,-30]))
#fixed_ppress_omega_phase = (2*np.pi*2, -np.pi/2)

#pumping = (0.5, PolyLine([0,0,10], [0,5,5]))


ppress_z = np.linspace(0,1,50)
avg_ppress_z_pairs = [[0,1],[0.4, 0.5]]
settlement_z_pairs = [[0,1],[0.4, 0.5]]
#tvals = np.linspace(0,3,10)
tvals = [0,0.05,0.1]+list(np.linspace(0.2,5,100))
tvals = np.linspace(0, 5, 100)
tvals = np.logspace(-2, 0.3,50)
ppress_z_tval_indexes = np.arange(len(tvals))[::len(tvals)//7]
#avg_ppress_z_pairs_tval_indexes = slice(None, None)#[0,4,6]
#settlement_z_pairs_tval_indexes = slice(None, None)#[0,4,6]

implementation='scalar'
implementation='vectorized'
#implementation='fortran'
#RLzero = -12.0
plot_properties={}

directory= r"C:\\Users\\Rohan Walker\\Documents\\temp" #may always need the r
save_data_to_file= True
save_figures_to_file= True
show_figures= True
overwrite=True

#prefix="silly"

#create_directory=True
#data_ext = '.csv'
#input_ext='.py'
figure_ext='.png'

    """)


    a = Speccon1dVRC(my_code)

    a.make_all()
