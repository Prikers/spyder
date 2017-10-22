# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
Namespace browser widget

This is the main widget used in the Variable Explorer plugin
"""

# Standard library imports
import os.path as osp

# Third library imports (qtpy)
from qtpy.compat import getsavefilename, getopenfilenames
from qtpy.QtCore import Qt, Signal, Slot
from qtpy.QtGui import QCursor
from qtpy.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QMenu,
                            QMessageBox, QToolButton, QVBoxLayout, QWidget)

# Local imports
from spyder.config.base import _, get_supported_types
from spyder.config.main import CONF
from spyder.py3compat import is_text_string, getcwd, to_text_string
from spyder.utils import encoding
from spyder.utils import icon_manager as ima
from spyder.utils.iofuncs import iofunctions
from spyder.utils.misc import fix_reference_name
from spyder.utils.programs import is_module_installed
from spyder.utils.qthelpers import (add_actions, create_action,
                                    create_toolbutton, create_plugin_layout)
from spyder.widgets.variableexplorer.collectionseditor import (
    RemoteCollectionsEditorTableView, VariableFinder)
from spyder.widgets.variableexplorer.importwizard import ImportWizard
from spyder.widgets.variableexplorer.utils import REMOTE_SETTINGS
from spyder.widgets.comboboxes import PatternComboBox


SUPPORTED_TYPES = get_supported_types()


class NamespaceBrowser(QWidget):
    """Namespace browser (global variables explorer widget)"""
    sig_option_changed = Signal(str, object)
    sig_collapse = Signal()
    
    def __init__(self, parent):
        QWidget.__init__(self, parent)
        
        self.shellwidget = None
        self.is_visible = True
        self.setup_in_progress = None

        # Remote dict editor settings
        self.check_all = None
        self.exclude_private = None
        self.exclude_uppercase = None
        self.exclude_capitalized = None
        self.exclude_unsupported = None
        self.excluded_names = None
        self.minmax = None
        
        # Other setting
        self.dataframe_format = None
        self.search_toolbar=False

        self.editor = None
        self.exclude_private_action = None
        self.exclude_uppercase_action = None
        self.exclude_capitalized_action = None
        self.exclude_unsupported_action = None

        self.filename = None

    def setup(self, check_all=None, exclude_private=None,
              exclude_uppercase=None, exclude_capitalized=None,
              exclude_unsupported=None, excluded_names=None,
              minmax=None, dataframe_format=None, search_toolbar=False):
        """
        Setup the namespace browser with provided settings.

        Args:
            dataframe_format (string): default floating-point format for 
                DataFrame editor
        """
        assert self.shellwidget is not None
        
        self.check_all = check_all
        self.exclude_private = exclude_private
        self.exclude_uppercase = exclude_uppercase
        self.exclude_capitalized = exclude_capitalized
        self.exclude_unsupported = exclude_unsupported
        self.excluded_names = excluded_names
        self.minmax = minmax
        self.dataframe_format = dataframe_format
        
        if self.editor is not None:
            self.editor.setup_menu(minmax)
            self.editor.set_dataframe_format(dataframe_format)
            self.exclude_private_action.setChecked(exclude_private)
            self.exclude_uppercase_action.setChecked(exclude_uppercase)
            self.exclude_capitalized_action.setChecked(exclude_capitalized)
            self.exclude_unsupported_action.setChecked(exclude_unsupported)
            self.refresh_table()
            return

        self.editor = RemoteCollectionsEditorTableView(
                        self,
                        data=None,
                        minmax=minmax,
                        shellwidget=self.shellwidget,
                        dataframe_format=dataframe_format)

        self.editor.sig_option_changed.connect(self.sig_option_changed.emit)
        self.editor.sig_files_dropped.connect(self.import_data)

        self.finder = VariableFinder(self.editor, self.editor.set_regex)
        self.editor.finder = self.finder
        #self.label_finder = QLabel(_('Search: '))

        # Setup layout
        self.hlayout1 = QHBoxLayout()
        self.hlayout2 = QHBoxLayout()
        vlayout = QVBoxLayout()
        #blayout = QHBoxLayout()
        layout1, layout2 = self.setup_toolbar(
                exclude_private, exclude_uppercase,
                exclude_capitalized, exclude_unsupported)
        for widget in layout1:
            self.hlayout1.addWidget(widget)
        for widget in layout2:
            self.hlayout2.addWidget(widget)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.addLayout(self.hlayout1)
        vlayout.addLayout(self.hlayout2)
        
        # Options menu
        options_button = create_toolbutton(self, text=_('Options'),
                                           icon=ima.icon('tooloptions'))
        options_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        editor = self.editor
        actions = [self.exclude_private_action, self.exclude_uppercase_action,
                   self.exclude_capitalized_action,
                   self.exclude_unsupported_action, None]
        if is_module_installed('numpy'):
            actions.append(editor.minmax_action)
        add_actions(menu, actions)
        options_button.setMenu(menu)

        self.hlayout1.addStretch()
        self.hlayout1.addWidget(options_button)

        layout = create_plugin_layout(vlayout, self.editor)
        self.show_search_toolbar(search_toolbar)
        self.setLayout(layout)

        self.sig_option_changed.connect(self.option_changed)
        
    def set_shellwidget(self, shellwidget):
        """Bind shellwidget instance to namespace browser"""
        self.shellwidget = shellwidget
        shellwidget.set_namespacebrowser(self)

    def setup_toolbar(self, exclude_private, exclude_uppercase,
                      exclude_capitalized, exclude_unsupported):
        """Setup toolbar"""
        self.setup_in_progress = True
        
        # Layout 1
        load_button = create_toolbutton(self, text=_('Import data'),
                                        icon=ima.icon('fileimport'),
                                        triggered=lambda: self.import_data())
        self.save_button = create_toolbutton(self, text=_("Save data"),
                            icon=ima.icon('filesave'),
                            triggered=lambda: self.save_data(self.filename))
        self.save_button.setEnabled(False)
        save_as_button = create_toolbutton(self,
                                           text=_("Save data as..."),
                                           icon=ima.icon('filesaveas'),
                                           triggered=self.save_data)
        reset_namespace_button = create_toolbutton(
                self, text=_("Reset the namespace"),
                icon=ima.icon('editclear'), triggered=self.reset_namespace)

        self.search_button = create_toolbutton(
                self, text=_("Search a variable"), icon=ima.icon('find'),
                toggled=self.show_search_toolbar)
        self.search_button.setCheckable(True)
        self.search_button.setChecked(self.search_toolbar) #TODO: self or passed?

        self.exclude_private_action = create_action(self,
                _("Exclude private references"),
                tip=_("Exclude references which name starts"
                            " with an underscore"),
                toggled=lambda state:
                self.sig_option_changed.emit('exclude_private', state))
        self.exclude_private_action.setChecked(exclude_private)
        
        self.exclude_uppercase_action = create_action(self,
                _("Exclude all-uppercase references"),
                tip=_("Exclude references which name is uppercase"),
                toggled=lambda state:
                self.sig_option_changed.emit('exclude_uppercase', state))
        self.exclude_uppercase_action.setChecked(exclude_uppercase)
        
        self.exclude_capitalized_action = create_action(self,
                _("Exclude capitalized references"),
                tip=_("Exclude references which name starts with an "
                      "uppercase character"),
                toggled=lambda state:
                self.sig_option_changed.emit('exclude_capitalized', state))
        self.exclude_capitalized_action.setChecked(exclude_capitalized)
        
        self.exclude_unsupported_action = create_action(self,
                _("Exclude unsupported data types"),
                tip=_("Exclude references to unsupported data types"
                            " (i.e. which won't be handled/saved correctly)"),
                toggled=lambda state:
                self.sig_option_changed.emit('exclude_unsupported', state))
        self.exclude_unsupported_action.setChecked(exclude_unsupported)
        
        layout1 = [load_button, self.save_button, save_as_button,
                   reset_namespace_button, self.search_button]

        # Layout 2
        #self.search_variable = PatternComboBox(
        #        self, tip=_("Search variable"), adjust_to_minimum=False)
        previous_button = create_toolbutton(
                self, text=_("Search next"), icon=ima.icon('ArrowUp'),
                triggered=self.find_previous)
        next_button = create_toolbutton(
                self, text=_("Search previous"), icon=ima.icon('ArrowDown'),
                triggered=self.find_next)
        close_button = create_toolbutton(
                self, text=_("Close toolbar"),
                icon=ima.icon('DialogCloseButton'), triggered=self.hide)

        layout2 = [self.finder, previous_button, next_button,
                   close_button]

        toolbar = (layout1, layout2)
        self.setup_in_progress = False
        
        return toolbar

    def option_changed(self, option, value):
        """Option has changed"""
        setattr(self, to_text_string(option), value)
        self.shellwidget.set_namespace_view_settings()
        self.refresh_table()

    def get_view_settings(self):
        """Return dict editor view settings"""
        settings = {}
        for name in REMOTE_SETTINGS:
            settings[name] = getattr(self, name)
        return settings

    def refresh_table(self):
        """Refresh variable table"""
        if self.is_visible and self.isVisible():
            self.shellwidget.refresh_namespacebrowser()
            try:
                self.editor.resizeRowToContents()
            except TypeError:
                pass

    def process_remote_view(self, remote_view):
        """Process remote view"""
        if remote_view is not None:
            self.set_data(remote_view)

    def set_var_properties(self, properties):
        """Set properties of variables"""
        if properties is not None:
            self.editor.var_properties = properties

    def set_data(self, data):
        """Set data."""
        if data != self.editor.model.get_data():
            self.editor.set_data(data)
            self.editor.adjust_columns()
        
    def collapse(self):
        """Collapse."""
        self.sig_collapse.emit()

    @Slot(bool)
    @Slot(list)
    def import_data(self, filenames=None):
        """Import data from text file."""
        title = _("Import data")
        if filenames is None:
            if self.filename is None:
                basedir = getcwd()
            else:
                basedir = osp.dirname(self.filename)
            filenames, _selfilter = getopenfilenames(self, title, basedir,
                                                     iofunctions.load_filters)
            if not filenames:
                return
        elif is_text_string(filenames):
            filenames = [filenames]

        for filename in filenames:
            self.filename = to_text_string(filename)
            ext = osp.splitext(self.filename)[1].lower()

            if ext not in iofunctions.load_funcs:
                buttons = QMessageBox.Yes | QMessageBox.Cancel
                answer = QMessageBox.question(self, title,
                            _("<b>Unsupported file extension '%s'</b><br><br>"
                              "Would you like to import it anyway "
                              "(by selecting a known file format)?"
                              ) % ext, buttons)
                if answer == QMessageBox.Cancel:
                    return
                formats = list(iofunctions.load_extensions.keys())
                item, ok = QInputDialog.getItem(self, title,
                                                _('Open file as:'),
                                                formats, 0, False)
                if ok:
                    ext = iofunctions.load_extensions[to_text_string(item)]
                else:
                    return

            load_func = iofunctions.load_funcs[ext]
                
            # 'import_wizard' (self.setup_io)
            if is_text_string(load_func):
                # Import data with import wizard
                error_message = None
                try:
                    text, _encoding = encoding.read(self.filename)
                    base_name = osp.basename(self.filename)
                    editor = ImportWizard(self, text, title=base_name,
                                  varname=fix_reference_name(base_name))
                    if editor.exec_():
                        var_name, clip_data = editor.get_data()
                        self.editor.new_value(var_name, clip_data)
                except Exception as error:
                    error_message = str(error)
            else:
                QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                QApplication.processEvents()
                error_message = self.shellwidget.load_data(self.filename, ext)
                self.shellwidget._kernel_reply = None
                QApplication.restoreOverrideCursor()
                QApplication.processEvents()
    
            if error_message is not None:
                QMessageBox.critical(self, title,
                                     _("<b>Unable to load '%s'</b>"
                                       "<br><br>Error message:<br>%s"
                                       ) % (self.filename, error_message))
            self.refresh_table()

    @Slot()
    def reset_namespace(self):
        warning = CONF.get('ipython_console', 'show_reset_namespace_warning')
        self.shellwidget.reset_namespace(silent=True, warning=warning)

    @Slot()
    def save_data(self, filename=None):
        """Save data"""
        if filename is None:
            filename = self.filename
            if filename is None:
                filename = getcwd()
            filename, _selfilter = getsavefilename(self, _("Save data"),
                                                   filename,
                                                   iofunctions.save_filters)
            if filename:
                self.filename = filename
            else:
                return False
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        QApplication.processEvents()

        error_message = self.shellwidget.save_namespace(self.filename)
        self.shellwidget._kernel_reply = None

        QApplication.restoreOverrideCursor()
        QApplication.processEvents()
        if error_message is not None:
            QMessageBox.critical(self, _("Save data"),
                            _("<b>Unable to save current workspace</b>"
                              "<br><br>Error message:<br>%s") % error_message)
        self.save_button.setEnabled(self.filename is not None)

    @Slot(bool)
    def show_search_toolbar(self, state):
        for index in range(self.hlayout2.count()):
            if state and self.isVisible() or not state:
                self.hlayout2.itemAt(index).widget().setVisible(state)
        self.finder.setFocus()

    def find_previous(self):
        data = self.editor.model.showndata.keys()
        text = self.search_variable.currentText()
        if len(text) == 0 or len(data) == 0:
            return
        results = get_close_matches(text, data, n=len(data), cutoff=0)
        self.editor.model.sort(column=-1, custom_key_order=results)
        return results

    def find_next(self):
        pass

    def hide(self):
        self.show_search_toolbar 
        self.search_button.setChecked(not self.search_button.isChecked())
