# -*- coding: utf-8 -*-
"""
DA-V LAN Discovery View
Table and card presentation for local network peers discovered via UDP Beacons and Subnet Sweeps.
"""

from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, Signal, Qt
)
from src.ui.theme import Theme


class DiscoveryView(QWidget):
    """View displaying local devices active on the LAN for one-click connection."""
    connect_peer_requested = Signal(str, int)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Dispositivos com DA-V Detectados na Rede Local (Beacon UDP):"))
        header_layout.addStretch()

        self.btn_refresh = QPushButton("Atualizar Lista (Varredura)")
        self.btn_refresh.setObjectName("secondaryBtn")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        header_layout.addWidget(self.btn_refresh)
        layout.addLayout(header_layout)

        self.tbl_peers = QTableWidget(0, 5)
        self.tbl_peers.setHorizontalHeaderLabels(["Nome do Host", "IP na Rede", "Porta", "Status", "Ação"])
        self.tbl_peers.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_peers.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_peers.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_peers.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_peers.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tbl_peers)

    def update_peers(self, peers: list):
        self.tbl_peers.setRowCount(len(peers))
        for row, p in enumerate(peers):
            self.tbl_peers.setItem(row, 0, QTableWidgetItem(p.get("node_name", "Desconhecido")))
            self.tbl_peers.setItem(row, 1, QTableWidgetItem(p.get("ip", "")))
            self.tbl_peers.setItem(row, 2, QTableWidgetItem(str(p.get("port", ""))))
            
            is_sharing = p.get("is_sharing", False)
            status_text = "Compartilhando (Ao Vivo)" if is_sharing else "Disponível"
            item_status = QTableWidgetItem(status_text)
            if is_sharing:
                item_status.setForeground(Theme.SYS["status_success"])
            self.tbl_peers.setItem(row, 3, item_status)

            btn_conn = QPushButton("Conectar")
            btn_conn.setObjectName("secondaryBtn")
            peer_ip = p.get("ip", "")
            peer_port = p.get("port", 9000)
            btn_conn.clicked.connect(lambda _, ip=peer_ip, port=peer_port: self.connect_peer_requested.emit(ip, port))
            self.tbl_peers.setCellWidget(row, 4, btn_conn)
