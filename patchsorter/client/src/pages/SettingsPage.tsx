import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listSettingsSettingsGet, updateSettingSettingsSettingKeyPatch } from '../api_client';
import { FormSelect, FormCheck, FormControl, Button, Card, Col, Row } from 'react-bootstrap';
import { useState, useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';

function SettingInput({ setting, onSaved }: { setting: import('../api_client').ResolvedSetting; onSaved: () => void }) {
    const [localValue, setLocalValue] = useState(setting.value);
    const isDirty = localValue !== setting.value;
    const isDifferentFromDefault = localValue !== setting.default;
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setLocalValue(setting.value);
    }, [setting.value]);

    const handleChange = (val: string) => {
        setLocalValue(val);
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            await updateSettingSettingsSettingKeyPatch({
                path: { setting_key: setting.key },
                body: { value: localValue },
                query: setting.project_id !== null ? { project_id: setting.project_id } : undefined,
            });
            toast.success(`Saved ${setting.key}`);
            onSaved();
        } catch (err: any) {
            toast.error(`Failed to save ${setting.key}: ${err?.message || 'Unknown error'}`);
        } finally {
            setSaving(false);
        }
    };

    const handleReset = async () => {
        setSaving(true);
        try {
            await updateSettingSettingsSettingKeyPatch({
                path: { setting_key: setting.key },
                body: { value: setting.default },
                query: setting.project_id !== null ? { project_id: setting.project_id } : undefined,
            });
            toast.success(`Reset ${setting.key} to default`);
            onSaved();
        } catch (err: any) {
            toast.error(`Failed to reset ${setting.key}: ${err?.message || 'Unknown error'}`);
        } finally {
            setSaving(false);
        }
    };

    const renderInput = () => {
        const baseProps = {
            value: localValue,
            onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => handleChange(e.target.value),
            disabled: setting.disabled ?? false,
            className: isDirty ? 'border-warning' : '',
        };

        switch (setting.type) {
            case 'enum':
                return (
                    <FormSelect {...baseProps}>
                        {setting.allowed_values?.map(v => (
                            <option key={v} value={v}>{v}</option>
                        ))}
                    </FormSelect>
                );
            case 'boolean':
                return (
                    <FormCheck
                        type="checkbox"
                        checked={localValue.toLowerCase() === 'true' || localValue === '1'}
                        onChange={(e) => handleChange(e.target.checked ? 'true' : 'false')}
                        disabled={setting.disabled ?? false}
                    />
                );
            case 'integer':
                return (
                    <FormControl
                        type="number"
                        {...baseProps}
                    />
                );
            case 'string':
            default:
                return (
                    <FormControl
                        type="text"
                        {...baseProps}
                    />
                );
        }
    };

    return (
        <div className="mb-3 p-3 border rounded">
            <div className="d-flex justify-content-between align-items-center mb-2">
                <strong>{setting.key}</strong>
                <span className="text-muted small">({setting.type})</span>
            </div>
            {setting.description && (
                <p className="text-muted small mb-2">{setting.description}</p>
            )}
            <div className="mb-2">
                {renderInput()}
            </div>
            <div className="d-flex gap-2">
                <small className="text-muted">Default: {setting.default}</small>
                {isDirty && (
                    <>
                        <Button
                            size="sm"
                            variant="primary"
                            disabled={saving}
                            onClick={handleSave}
                        >
                            {saving ? 'Saving...' : 'Save'}
                        </Button>
                    </>
                )}
                {isDifferentFromDefault && (
                    <Button
                        size="sm"
                        variant="outline-secondary"
                        disabled={saving}
                        onClick={handleReset}
                    >
                        {saving ? 'Saving...' : 'Reset'}
                    </Button>
                )}
            </div>
        </div>
    );
}

export default function SettingsPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>();
    const projectId = projectIdParam ? Number(projectIdParam) : null;
    const queryClient = useQueryClient();

    const { data: settings, isLoading } = useQuery({
        queryKey: ['settings', projectId],
        queryFn: () =>
            listSettingsSettingsGet({
                query: projectId ? { project_id: Number(projectId) } : undefined,
            }).then(r => r.data),
    });

    const handleSaved = () => {
        queryClient.invalidateQueries({ queryKey: ['settings', projectId] });
    };

    if (isLoading) {
        return <div className="container mt-4">Loading...</div>;
    }

    if (!settings) {
        return null;
    }

    const appSettings = settings.filter(s => s.scope === 'application');
    const projectSettings = settings.filter(s => s.scope === 'project');

    return (
        <div className="container-fluid mt-4">
            <Row>
                <Col md={6}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Application Settings</h5>
                        </Card.Header>
                        <Card.Body>
                            {appSettings.length === 0 && <p className="text-muted">No application settings.</p>}
                            {appSettings.map(setting => (
                                <SettingInput
                                    key={setting.key}
                                    setting={setting}
                                    onSaved={handleSaved}
                                />
                            ))}
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={6}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Project Settings</h5>
                        </Card.Header>
                        <Card.Body>
                            {projectSettings.length === 0 && <p className="text-muted">Enter a project from the <Link to="/">landing page</Link> and click "Project Settings" to view and modify project settings.</p>}
                            {projectSettings.map(setting => (
                                <SettingInput
                                    key={setting.key}
                                    setting={setting}
                                    onSaved={handleSaved}
                                />
                            ))}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
        </div>
    );
}
