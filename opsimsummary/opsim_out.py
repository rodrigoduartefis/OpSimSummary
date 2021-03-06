"""
This module deals with representing the data in an OpSim output (to the extent
we will care about it). A description of the OpSim output can be found at
(opsim description)[https://www.lsst.org/scientists/simulations/opsim/summary-table-column-descriptions-v335]

In brief, we will use two tables from the OpSim output:
    - Summary which has the desired information
    - Proposals which contains a dictionary to interpreting the `propID` column
        of Summary.
"""
from __future__ import division, print_function, unicode_literals
__all__ = ['OpSimOutput']
import numpy as np
import pandas as pd
from sqlalchemy import create_engine


class OpSimOutput(object):
    """
    Class representing a subset of the output of the OpSim including
    information from the Summary and Proposal Tables with the subset taken over
    the proposals


    Attribute
    ---------
    opsimversion: {'lsstv3'|'sstf'|'lsstv4'}
        version of OpSim corresponding to the output format.
    summary : `pd.DataFrame`
        selected records from the Summary Table of pointings
    propIDDict : dict
        dictionary with strings as keys and integers used in the Summary
        Table to denote these proposals
    proposalTable : `pd.DataFrame`
        the propsal table in the output
    subset: string
        subset of proposals included in this class
    propIDs : list of integers
        integers corresponding to the subset selected through proposals
    zeroDDFDithers : bool, defaults to True
        if True, set dithers in DDF to 0, by setting ditheredRA,
        ditheredDec to fieldRA, fieldDec. This should only be used for
        opsimversion='lsstv3'. For opsimversion='sstf' or 'lsstv4', this
        will be set to False despite inputs, since this is already done, and
        cannot be done with the inputs.
    """
    def __init__(self, summary=None, propIDDict=None, proposalTable=None,
                 subset=None, propIDs=None, zeroDDFDithers=True,
                 opsimversion='lsstv3'):

        self.opsimversion = opsimversion
        self.propIDDict = propIDDict
        self.proposalTable = proposalTable
        if opsimversion in ('sstf', 'lsstv4'):
            zeroDDFDithers = False
            ss = 'Warning: Input is zeroDDFDithers = True. But opsimversion is'
            ss += '{} for which this must be False. Setting to False and proceeding\n'.format(opsimversion)
            print(ss) 

        if zeroDDFDithers:
            ddfPropID = self.propIDDict['ddf']
            print('ddfPropID should be 5 ?', ddfPropID)
            print('the columns in summary are ', summary.columns)
            ddfidx = summary.query('propID == @ddfPropID').index
            print('ddf indx', ddfidx)
            summary.loc[ddfidx, 'ditheredRA'] = summary.loc[ddfidx, 'fieldRA']
            summary.loc[ddfidx, 'ditheredDec'] = summary.loc[ddfidx, 'fieldDec']

        # Have a clear unambiguous ra, dec in radians following LSST convention
        if self.opsimVars['angleUnits'] == 'degrees':
            summary['_ra'] = np.radians(summary['ditheredRA'])
            summary['_dec'] = np.radians(summary['ditheredDec'])
        elif self.opsimVars['angleUnits'] == 'radians':
            summary['_ra'] = summary['ditheredRA']
            summary['_dec'] = summary['ditheredDec']
        else:
            raise ValueError('angle unit of ra and dec Columns not recognized\n')

        self.summary = summary
        self.allowed_subsets = self.get_allowed_subsets()
        self.subset = subset
        self._propID = propIDs

    @property
    def opsimVars(self):
        """
        a set of opsim version dependent variables
        """
        opsimvars = self.get_opsimVariablesForVersion(self.opsimversion)
        return opsimvars

    @classmethod
    def fromOpSimDB(cls, dbname, subset='combined',
                    tableNames=('Summary', 'Proposal'),
                    propIDs=None, zeroDDFDithers=True,
                    opsimversion='lsstv3'):
        """
        Class Method to instantiate this from an OpSim sqlite
        database output

        Parameters
        ----------
        dbname : string
            absolute path to database file
        subset : string, optional, defaults to 'combined'
            one of {'_all', 'unique_all', 'wfd', 'ddf', 'combined'}
            determines a sequence of propIDs for selecting observations
            appropriate for the OpSim database in use
        propIDs : sequence of integers, defaults to None
            proposal ID values. If present, overrides the use of subset
        tableNames : tuple of strings, defaults to ('Summary', 'Proposal')
            names of tables read from the OpSim database
        zeroDDFDithers : bool, defaults to True
            if True, set dithers in DDF to 0, by setting ditheredRA,
            ditheredDec to fieldRA, fieldDec
        opsimversion: {'lsstv3'|'sstf'|'lsstv4'}
            version of OpSim corresponding to the output format.
        """
        if opsimversion in ('sstf', 'lsstv4'):
            tableNames=('Summary', 'Proposal')

        # Because this is in the class method, I am using the staticmethod
        # rather than a property
        opsimVars = cls.get_opsimVariablesForVersion(opsimversion)

        # Check that subset parameter is legal
        allowed_subsets = cls.get_allowed_subsets()
        subset = subset.lower()
        if subset not in allowed_subsets:
            raise NotImplementedError('subset {} not implemented'.\
                                      format(subset))

        # Prepend the abs path with sqlite for use with sqlalchemy
        if not dbname.startswith('sqlite'):
            dbname = 'sqlite:///' + dbname
        print(' reading from database {}'.format(dbname))
        engine = create_engine(dbname, echo=False)

        # Read the proposal table to find out which propID corresponds to
        # the subsets requested
        proposals = pd.read_sql_table('Proposal', con=engine)
        propDict = cls.get_propIDDict(proposals, opsimversion=opsimversion)

        # Seq of propIDs consistent with subset
        _propIDs = cls.propIDVals(subset, propDict, proposals)
        # If propIDs and subset were both provided, override subset propIDs
        propIDs = cls._overrideSubsetPropID(propIDs, _propIDs)

        # Do the actual sql queries or table reads
        summaryTableName = opsimVars['summaryTableName']
        propIDNameInSummary = opsimVars['propIDNameInSummary']
        if subset in ('_all', 'unique_all'):
            # In this case read everything (ie. table read)
            summary = pd.read_sql_table(summaryTableName, con=engine)

        elif subset in ('ddf', 'wfd', 'combined'):

            # In this case use sql queries rather than reading the whole table
            # obtain propIDs in strings for sql queries
            pidString = ', '.join(list(str(pid) for pid in propIDs))
            sql_query = 'SELECT * FROM {0} WHERE {1}'.format(summaryTableName,
                                                             propIDNameInSummary
                                                            )
            sql_query += ' in ({})'.format(pidString)

            # If propIDs were passed to the method, this would be used
            print(sql_query)
            summary = pd.read_sql_query(sql_query, con=engine)
        else:
            raise NotImplementedError()

        replacedict = dict()
        replacedict[opsimVars['obsHistID']] = 'obsHistID'
        replacedict[opsimVars['propIDNameInSummary']] = 'propID'
        replacedict[opsimVars['pointingRA']] = 'ditheredRA'
        replacedict[opsimVars['pointingDec']] = 'ditheredDec'
        replacedict[opsimVars['expMJD']] = 'expMJD'
        replacedict[opsimVars['FWHMeff']] = 'FWHMeff'
        replacedict[opsimVars['filtSkyBrightness']] = 'filtSkyBrightness'
        summary.rename(columns=replacedict, inplace=True)
        if subset != '_all':
            # Drop duplicates unless this is to write out the entire OpSim
            summary = cls.dropDuplicates(summary, propDict, opsimversion)

        summary.set_index('obsHistID', inplace=True)

        del summary['index']
        return cls(propIDDict=propDict,
                   summary=summary,
                   zeroDDFDithers=zeroDDFDithers,
                   proposalTable=proposals, subset=subset,
                   opsimversion=opsimversion)

    @staticmethod
    def dropDuplicates(df, propIDDict, opsimversion):
        """
        drop duplicates ensuring keeping identity of ddf visits

        Parameters
        ----------
        df : `pd.DataFrame`
        propIDDict : dict

        Returns
        -------
        `pd.DataFrame` with the correct propID and duplicates dropped
        """
        if opsimversion == 'sstf':
            return df

        # As duplicates are dropped in order, reorder IDs so that
        # DDF is lowest, WFD next lowest, everything else as is
        minPropID = df.propID.min()
        ddfID = propIDDict['ddf']
        wfdID = propIDDict['wfd']
        ddfPropID = minPropID - 1
        wfdPropID = minPropID - 2

        ddfmask = df.propID == ddfID
        wfdmask = df.propID == wfdID
        df.loc[ddfmask, 'propID'] = ddfPropID
        df.loc[wfdmask, 'propID'] = wfdPropID

        # drop duplicates keeping the lowest transformed propIDs so that all
        # WFD visits remain, DDF visits which were duplicates of WFD visits are
        # dropped, etc.

        # df = df.drop_duplicates(subset='obsHistID', keep='first', inplace=False)
        df = df.reset_index().drop_duplicates(subset='obsHistID',
                                              keep='first')#.set_index('obsHistID')

        # reset the propIDs to values in the OpSim output
        ddfmask = df.propID == ddfPropID
        wfdmask = df.propID == wfdPropID
        df.loc[ddfmask, 'propID'] = ddfID
        df.loc[wfdmask, 'propID'] = wfdID
        # df.loc[df.query('propID == @ddfPropID').index, 'propID'] = ddfID
        # df.loc[df.query('propID == @wfdPropID').index, 'propID'] = wfdID
        df.sort_values(by='expMJD', inplace=True)
        return df


    @classmethod
    def fromOpSimHDF(cls, hdfName, subset='combined',
                     tableNames=('Summary', 'Proposal'),
                     propIDs=None):
        """
        Construct an instance of a subset of the OpSim
        Output from a serialization in the format of hdf

        Parameters
        ----------
        hdfName :
        subset :
        tableNames :
        propIDs :
        """
        raise NotImplementedError('Not quite working at this moment')
        allowed_subsets = cls.get_allowed_subsets()
        subset = subset.lower()
        if subset not in allowed_subsets:
            raise NotImplementedError('subset {} not implemented'.\
                      format(subset))
        # The hdf representation is assumed to be a faithful representation of
        # the OpSim output
        summarydf = pd.read_hdf(hdfName, key='Summary')

        if 'obsHistID' not in summarydf.columns:
            summarydf.reset_index(inplace=True)
            if 'obsHistID' not in summarydf.columns:
                raise NotImplementedError('obsHistID is not in columns')

        try:
            proposals = pd.read_hdf(hdfName, key='Proposal')
            print('read in proposal')
            propDict = cls.get_propIDDict(proposal)
            print('read in proposal')
            print(subset, propDict)
            _propIDs = cls.propIDVals(subset, propDict, proposals)
        except:
            print('Proposal not read')
            pass

        propIDs = cls._overrideSubsetPropID(propIDs, _propIDs)

        if propIDs is not None:
            if not isinstance(propIDs, list):
                propIDs = propIDs.tolist()
            print('propIDs', propIDs, type(propIDs), type(propIDs[0]))
            print('summarydf cols', summarydf.columns)
            query_str = 'propID == @propIDs'
            print('query_str', query_str)
            print(' Num entries ', len(summarydf))
            summary = summarydf.query(query_str)
        else:
            summary = summarydf
        if propIDs is None and subset not in ('_all', 'unique_all'):
            raise ValueError('No sensible propID and subset combination found')

        if subset != '_all':
            # Usually drop the OpSim duplicates
            summary.drop_duplicates(subset='obsHistID', inplace=True)

        summary.set_index('obsHistID', inplace=True)
        return cls(propIDDict=propDict, summary=summary,
                   proposalTable=proposals, subset=subset)

    @property
    def propIds(self):
        """
        list of values in propID Column of the Summary Table of OpSim
        to be considered for this class, either because they were directly
        provided or through the subset argument.
        """
        if self._propID is not None:
            return self._propID
        elif self.subset is not None and self.propIDDict is not None:
            return self.propIDVals(self.subset, self.propIDDict, self.proposalTable)

    def writeOpSimHDF(self, hdfName):
        """
        Serialize the OpSim output to hdf format in a welldefined way
        The output hdf file has two keys: 'Summary' and 'Proposal'
        """
        if self.subset != '_all':
            raise ValueError('Should be Done only for self.subset == _all')
        self.summary.to_hdf(hdfName, key='Summary', append=False)
        self.proposalTable.to_hdf(hdfName, key='Proposal', append=False)

    @staticmethod
    def _overrideSubsetPropID(propIDs, _propIDs):
        if propIDs is None:
            propIDs = _propIDs
        else:
            if np.asarray(propIDs).sort() != np.asarray(_propIDs).sort():
                raise Warning('argument propIDs and _propIDs do not match')
        return propIDs

    @staticmethod
    def get_allowed_subsets():
        return ('_all', 'ddf', 'wfd', 'combined', 'unique_all')

    @staticmethod
    def get_propIDDict(proposalDF, opsimversion='lsstv3'):
        """
        Return a dictionary with keys 'ddf', ad 'wfd' with the proposal IDs
        corresponding to deep drilling fields (ddf) and universal cadence (wfd) 

        Parameters
        ----------
        proposalDF : `pd.DataFrame`, mandatory
            a dataframe with the Proposal Table of the OpSim Run.
        opsimversion: {'lsstv3'|'sstf'|'lsstv4'}, defaults to 'lsstv3'
            version of opsim from which output is drawn
        Returns
        -------
        dictionary with keys 'wfd' and 'ddf' with values given by integers
            corresponding to propIDs for these proposals
        """
        oss_wfdName = 'wfd'
        oss_ddfName = 'ddf'

        df = proposalDF
        mydict = dict()
        if opsimversion == 'lsstv3':
            propName = 'propConf'
            propIDName = 'propID'
            ops_wfdname = 'conf/survey/Universal-18-0824B.conf'
            ops_ddfname = 'conf/survey/DDcosmology1.conf'
        elif opsimversion == 'sstf':
            propName = 'propName'
            propIDName = 'propId'
            ops_wfdname = 'WideFastDeep'
            ops_ddfname = 'Deep Drilling'
        elif opsimversion == 'lsstv4':
            propName = 'propName'
            propIDName = 'propId'
            ops_wfdname = 'WideFastDeep'
            ops_ddfname = 'DeepDrillingCosmology1'
        else:
            raise NotImplementedError('`get_propIDDict` is not implemented for this `opsimversion`')

        # Rename version based proposal names to internal values
        for idx, row in df.iterrows():
            # remember in enigma outputs, these came with `..` in the beginning
            if ops_wfdname in row[propName]:
                df.loc[idx, propName] = oss_wfdName
            elif ops_ddfname in row[propName]:
                df.loc[idx, propName] = oss_ddfName
            else:
                pass
        return dict(df.set_index(propName)[propIDName])

    @staticmethod
    def get_opsimVariablesForVersion(opsimversion='lsstv3'):
        if opsimversion == 'lsstv3':
            x = dict(summaryTableName='Summary',
                     obsHistID='obsHistID',
                     propName='propConf',
                     propIDName='propID',
                     propIDNameInSummary='propID',
                     ops_wfdname='conf/survey/Universal-18-0824B.conf',
                     ops_ddfname='conf/survey/DDcosmology1.conf',
                     expMJD='expMJD',
                     FWHMeff='FWHMeff',
                     pointingRA='ditheredRA',
                     pointingDec='pointingDec',
                     filtSkyBrightness='filtSkyBrightness',
                     angleUnits='radians')
        elif opsimversion == 'sstf':
            x = dict(summaryTableName='SummaryAllProps',
                     obsHistID='observationId',
                     propName='propName',
                     propIDName='propId',
                     propIDNameInSummary='proposalId',
                     ops_wfdname='WideFastDeep',
                     ops_ddfname='Deep Drilling',
                     expMJD='observationStartMJD',
                     FWHMeff='seeingFwhmEff',
                     pointingRA='fieldRA',
                     pointingDec='fieldDec',
                     filtSkyBrightness='skyBrightness',
                     angleUnits='degrees')
        elif opsimversion == 'lsstv4':
            x = dict(summaryTableName='SummaryAllProps',
                     obsHistID='observationId',
                     propName='propName',
                     propIDName='propId',
                     propIDNameInSummary='proposalId',
                     ops_wfdname='WideFastDeep',
                     ops_ddfname='DeepDrillingCosmology1',
                     expMJD='observationStartMJD',
                     FWHMeff='seeingFwhmEff',
                     pointingRA='fieldRA',
                     pointingDec='fieldDec',
                     filtSkyBrightness='skyBrightness',
                     angleUnits='degrees')
        else:
            raise NotImplementedError('`get_propIDDict` is not implemented for this `opsimversion`')
        return x

    @staticmethod
    def propIDVals(subset, propIDDict, proposalTable):
        """
        Parameters: 
        ----------
        subset : string
            must be member of OpSimOutput.allowed_subsets()
        propIDDict : dictionary, mandatory
            must have subset as a key, and an integer or seq of ints
            as values
        proposalTable : `pd.DataFrame`
            Dataframe representing the proposal table in the OpSim datbase
            output

        Returns:
        -------
        list of propID values (integers) associated with the subset
        """
        if subset is None:
            raise ValueError('subset arg in propIDVals cannot be None')

        if subset.lower() in ('ddf', 'wfd'):
            return [propIDDict[subset.lower()]]
        elif subset.lower() == 'combined':
            return [propIDDict['ddf'], propIDDict['wfd']] 
        elif subset.lower() in ('_all', 'unique_all'):
            if proposalTable is not None:
                return proposalTable.propID.values
            else:
                return None
        else:
            raise NotImplementedError('value of subset Not recognized')
 
def OpSimDfFromFile(fname, ftype='hdf', subset='Combined'):
    """
    read a serialized form of the OpSim output into `pd.DataFrame`
    and return a subset of interest

    Parameters
    ----------
    fname : string, mandatory
        absolute path to serialized form of the OpSim database
    ftype : {'sqliteDB', 'ASCII', 'hdf'}
        The kind of serialized version being read from.
            'sqliteDB' : `LSST` project supplied OpSim output format for
                baseline cadences (eg. enigma_1189, minion_1016, etc.) 
            'ASCII' : `LSST` project supplied OpSim output format used in
                older OpSim outputs eg. OpSim v 2.168 output
            'hdf' : `hdf` files written out by `OpSimSummary`
    subset : {'Combined', 'DDF', 'WFD' , 'All'}, defaults to 'Combined' 
        Type of OpSim output desired in the dataframe
        'Combined' : unique pointings in WFD + DDF 
        'WFD' : Unique pointings in WFD
        'DDF' : Unique pointings in DDF Cosmology
        'All' : Entire Summary Table From OpSim
    """
    print('This seems to have changed since first written, fixing not a priority')
    raise NotImplementedError('This seems to have changed since first written')
    if ftype == 'sqlite':
        dbname = 'sqlite:///' + fname
        engine = create_engine(dbname, echo=False)
        proposalTable =  pd.read_sql_table('Proposal', con=engine)

        # if subset == 'DDF':
        #    sql

    elif ftype == 'hdf' :
        pass
    elif ftype == 'ASCII':
        pass
    else:
        raise NotImplementedError('ftype {} not implemented'.format(ftype))
