import {
    Button,
    ButtonGroup,
    FormControl,
    InputGroup,
    Modal
} from "react-bootstrap";

import React from "react";

class BackupModal extends React.Component {
    constructor(props) {
        super(props);

        this.state = {
            backups: [],
            backupName: ""
        };
    }

    componentDidUpdate(prevProps) {
        if (prevProps.show != this.props.show) this.refreshBackups();
    }

    refreshBackups() {
        pywebview.api
            .get_backups()
            .then(backups => this.setState({ backups, backupName: "" }));
    }

    render() {
        return (
            <Modal show={this.props.show}>
                <Modal.Header closeButton>
                    <Modal.Title>Backup and Restore Mods</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>
                        Here you can backup and restore entire mod
                        configurations. The backups are complete and exact: what
                        you restore will be identical to what you backed up.
                    </p>
                    <hr />
                    <div className="h5">Create Backup</div>
                    <InputGroup className="mb-3">
                        <FormControl
                            placeholder="Backup name"
                            value={this.state.backupName}
                            onChange={e =>
                                this.setState({ backupName: e.target.value })
                            }
                        />
                        <InputGroup.Append>
                            <Button
                                variant="primary"
                                onClick={() =>
                                    this.props.onCreate(
                                        this.state.backupName,
                                        "create"
                                    )
                                }>
                                Create
                            </Button>
                        </InputGroup.Append>
                    </InputGroup>
                    <hr />
                    <div className="h5">Restore Backup</div>
                    {this.state.backups.length > 0 ? (
                        this.state.backups.map(backup => (
                            <div
                                className="d-flex flex-row align-items-center mb-1"
                                key={backup.path}>
                                <span>
                                    {backup.name.replace("_", " ")}{" "}
                                    <small>({backup.num} mods)</small>
                                </span>
                                <div className="flex-grow-1"> </div>
                                <ButtonGroup size="xs">
                                    <Button
                                        variant="success"
                                        onClick={() =>
                                            this.props.onRestore(
                                                backup,
                                                "restore"
                                            )
                                        }>
                                        <i className="material-icons">
                                            settings_backup_restore
                                        </i>
                                    </Button>
                                    <Button
                                        variant="danger"
                                        onClick={() =>
                                            this.props.onDelete(
                                                backup,
                                                "delete"
                                            )
                                        }>
                                        <i className="material-icons">delete</i>
                                    </Button>
                                </ButtonGroup>
                            </div>
                        ))
                    ) : (
                        <p>No backups yet</p>
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={this.props.onClose}>
                        Close
                    </Button>
                </Modal.Footer>
            </Modal>
        );
    }
}

export default BackupModal;