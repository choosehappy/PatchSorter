import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listSettingsSettingsGet, updateSettingSettingsSettingKeyPatch } from '../api_client';
import { FormSelect, FormCheck, FormControl, Button, Card, Col, Row } from 'react-bootstrap';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

function SettingInput({ setting, onDirtyChange }: { setting: import('../api_client').ResolvedSetting; onDirtyChange: (key: string, isDirty: boolean) => void }) {
    const [localValue, setLocalValue] = useState(setting.value);
    const isDirty = localValue !== setting.value;

    const handleChange = (val: string) => {
        setLocalValue(val);
        onDirtyChange(setting.key, val !== setting.value);
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
                    <Button
                        size="sm"
                        variant="outline-secondary"
                        onClick={() => {
                            setLocalValue(setting.value);
                            onDirtyChange(setting.key, false);
                        }}
                    >
                        Reset
                    </Button>
                )}
            </div>
        </div>
    );
}

export default function SettingsPage() {
    const [searchParams] = useSearchParams();
    const projectId = searchParams.get('project_id');
    const queryClient = useQueryClient();

    const { data: settings, isLoading } = useQuery({
        queryKey: ['settings', projectId],
        queryFn: () =>
            listSettingsSettingsGet({
                query: projectId ? { project_id: Number(projectId) } : undefined,
            }).then(r => r.data),
    });

    const updateMutation = useMutation({
        mutationFn: async ({ key, value, pid }: { key: string; value: string; pid: number | null }) => {
            const response = await updateSettingSettingsSettingKeyPatch({
                path: { setting_key: key },
                body: { value },
                query: pid !== null ? { project_id: pid } : undefined,
            });
            return response.data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['settings', projectId] });
        },
    });

    const [dirty, setDirty] = useState<Set<string>>(new Set());

    const handleDirtyChange = (key: string, isDirty: boolean) => {
        setDirty(prev => {
            const next = new Set(prev);
            if (isDirty) {
                next.add(key);
            } else {
                next.delete(key);
            }
            return next;
        });
    };

    if (isLoading) {
        return <div className="container mt-4">Loading...</div>;
    }

    if (!settings) {
        return null;
    }

    const appSettings = settings.filter(s => s.scope === 'application');
    const projectSettings = settings.filter(s => s.scope === 'project');

    const handleSaveAll = (sectionSettings: import('../api_client').ResolvedSetting[]) => {
        const sectionDirty = sectionSettings.filter(s => dirty.has(s.key));
        if (sectionDirty.length === 0) return;

        Promise.all(
            sectionDirty.map(s =>
                updateMutation.mutateAsync({ key: s.key, value: s.value, pid: s.project_id ?? null })
            )
        ).catch(err => {
            console.error('Failed to save settings:', err);
        });
    };

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
                                    onDirtyChange={handleDirtyChange}
                                />
                            ))}
                            {appSettings.length > 0 && (
                                <Button
                                    variant="primary"
                                    onClick={() => handleSaveAll(appSettings)}
                                    disabled={appSettings.every(s => !dirty.has(s.key))}
                                >
                                    Save Application Settings
                                </Button>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
                <Col md={6}>
                    <Card>
                        <Card.Header>
                            <h5 className="mb-0">Project Settings</h5>
                        </Card.Header>
                        <Card.Body>
                            {projectSettings.length === 0 && <p className="text-muted">No project settings.</p>}
                            {projectSettings.map(setting => (
                                <SettingInput
                                    key={setting.key}
                                    setting={setting}
                                    onDirtyChange={handleDirtyChange}
                                />
                            ))}
                            {projectSettings.length > 0 && (
                                <Button
                                    variant="primary"
                                    onClick={() => handleSaveAll(projectSettings)}
                                    disabled={projectSettings.every(s => !dirty.has(s.key))}
                                >
                                    Save Project Settings
                                </Button>
                            )}
                        </Card.Body>
                    </Card>
                </Col>
            </Row>
        </div>
    );
}
